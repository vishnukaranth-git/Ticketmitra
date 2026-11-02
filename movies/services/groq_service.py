import json
import logging
import re
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


class GroqService:
    """Service to interact with Groq AI API for cinematic analysis of movies."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or getattr(settings, 'GROQ_API_KEY', '').strip()
        self.model = model or getattr(settings, 'GROQ_MODEL', 'openai/gpt-oss-120b').strip()
        self._client = None

    @property
    def client(self):
        if self._client is None and self.api_key:
            try:
                from groq import Groq
                self._client = Groq(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key and self.client)

    def analyze_movie(
        self,
        title: str,
        overview: str,
        release_date: str | None = None,
        genres: str | None = None,
        rating: float | None = None,
        is_upcoming: bool = False,
    ) -> dict[str, Any]:
        """
        Analyzes a currently released or upcoming movie.
        Returns a dictionary with:
        - verdict: Short 1-sentence critical verdict.
        - audience_fit: Ideal target audience description.
        - highlights: List of 2-3 key thematic highlights.
        - theatrical_recommendation: e.g. 'Must Experience in Theaters (IMAX/Dolby)', etc.
        """
        if not self.is_available():
            return self._generate_rule_based_fallback(title, overview, genres, is_upcoming)

        context_type = "Upcoming Theatrical Release" if is_upcoming else "Currently Released Theatrical Movie"
        prompt = f"""You are TicketMitra's senior cinema critic and AI film analyst.
Analyze the following movie for Indian cinema viewers:

Movie Title: {title}
Status: {context_type}
Release Date: {release_date or 'TBA'}
Genres: {genres or 'Cinema'}
TMDB Rating: {rating or 'N/A'}
Synopsis: {overview or 'No synopsis available.'}

Provide your analysis in the following structured format:
VERDICT: (One concise, captivating sentence explaining why audiences should watch it)
AUDIENCE: (Who will enjoy this film most)
HIGHLIGHTS: (Comma-separated 3 highlights)
RECOMMENDATION: (One of: Must Experience in Theaters, Big-Screen Spectacle, Recommended Family Watch, Anticipated Upcoming Blockbuster)"""

        try:
            chat_completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional cinema curator for TicketMitra. Provide concise, compelling film critiques.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
            )
            raw_text = chat_completion.choices[0].message.content or ""
            parsed = self._parse_analysis_response(raw_text)
            if parsed.get("verdict"):
                return parsed

        except Exception as e:
            logger.warning(f"Groq analysis error for '{title}': {e}")

        return self._generate_rule_based_fallback(title, overview, genres, is_upcoming)

    def _parse_analysis_response(self, text: str) -> dict[str, Any]:
        """Parses structured text or JSON from model output."""
        result: dict[str, Any] = {}
        if not text:
            return result

        clean = text.strip()
        # Check for JSON block
        if "{" in clean and "}" in clean:
            try:
                start = clean.find("{")
                end = clean.rfind("}") + 1
                json_data = json.loads(clean[start:end])
                if isinstance(json_data, dict):
                    return {
                        "verdict": str(json_data.get("verdict", "")).strip(),
                        "audience_fit": str(json_data.get("audience_fit", "")).strip(),
                        "highlights": json_data.get("highlights", [])[:3],
                        "theatrical_recommendation": str(
                            json_data.get("theatrical_recommendation", "Recommended")
                        ).strip(),
                    }
            except Exception:
                pass

        # Regex extract sections ignoring markdown bold asterisks
        def extract_field(field_name: str, fallback_field: str | None = None):
            pattern = rf"(?:\*\*|\#\#)?\s*{field_name}\s*(?:\*\*|\#\#)?:\s*(.*?)(?=\n(?:\*\*|\#\#)?[A-Z]+(?:\*\*|\#\#)?:|$)"
            m = re.search(pattern, clean, re.DOTALL | re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                # Clean stray markdown
                val = re.sub(r"^\*+|\*+$", "", val).strip()
                val = re.sub(r"\s+", " ", val)
                return val
            return ""

        verdict = extract_field("VERDICT")
        audience = extract_field("AUDIENCE")
        highlights_raw = extract_field("HIGHLIGHTS")
        recommendation = extract_field("RECOMMENDATION")

        if verdict:
            result["verdict"] = verdict
        if audience:
            result["audience_fit"] = audience
        if highlights_raw:
            cleaned_hl = [
                re.sub(r"^\*+|\*+$", "", h).strip()
                for h in highlights_raw.split(",")
                if h.strip()
            ]
            result["highlights"] = cleaned_hl[:3]
        if recommendation:
            result["theatrical_recommendation"] = recommendation

        return result

    def _generate_rule_based_fallback(
        self, title: str, overview: str, genres: str | None = None, is_upcoming: bool = False
    ) -> dict[str, Any]:
        """Provides an editorial fallback if API is unreachable."""
        genre_str = (genres or "cinematic").split(",")[0].strip()
        if is_upcoming:
            return {
                "verdict": f"A highly anticipated {genre_str.lower()} theatrical event poised to captivate Indian cinema audiences upon arrival.",
                "audience_fit": f"Ideal for lovers of {genre_str.lower()} stories looking for their next big-screen release.",
                "highlights": ["Anticipated Release", f"{genre_str} Thrills", "Theatrical Run"],
                "theatrical_recommendation": "Anticipated Upcoming Blockbuster",
            }
        return {
            "verdict": f"A compelling {genre_str.lower()} theatrical showcase delivering dynamic entertainment on the big screen.",
            "audience_fit": f"Recommended for cinema enthusiasts who appreciate engaging {genre_str.lower()} storytelling.",
            "highlights": ["Big Screen Experience", "Engaging Narrative", "Stunning Visuals"],
            "theatrical_recommendation": "Must Experience in Theaters",
        }

    def analyze_movie_object(self, movie) -> dict[str, Any]:
        """Convenience method to analyze a Movie model instance directly."""
        from django.utils import timezone
        genres_str = ", ".join([g.name for g in movie.genres.all()]) if hasattr(movie, 'genres') else ''
        is_up = (movie.status == 'UPCOMING') or (movie.release_date and movie.release_date > timezone.now().date())
        rating_val = float(movie.tmdb_rating or movie.rating or 0.0)
        return self.analyze_movie(
            title=movie.get_display_title(),
            overview=movie.description or '',
            release_date=str(movie.release_date) if movie.release_date else None,
            genres=genres_str,
            rating=rating_val if rating_val > 0 else None,
            is_upcoming=is_up,
        )


GroqMovieAnalyzer = GroqService

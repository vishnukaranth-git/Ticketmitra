with open('Ticketmitra/templates/admin/payments_list.html', 'r', encoding='utf-8') as f:
    c = f.read()

target = """                  <!-- Inspect Action -->
                  <td style="padding: 12px 18px; vertical-align: middle; text-align: right;">
                    <button type="button" class="tm-btn tm-btn-ghost py-1 px-2 small" onclick="openPaymentDetails('{{ p.id }}', '{{ p.user.username }}', '{{ p.amount }}', '{{ p.currency|default:'INR' }}', '{{ p.status }}', '{{ p.payment_id|default:''|escapejs }}', '{{ p.order_id|default:''|escapejs }}', '{{ p.transaction_id|default:''|escapejs }}', '{{ p.created_at|date:'M d, Y H:i:s' }}')" title="View Full Payment Metadata">
                      <i class="fas fa-eye"></i> Details
                    </button>
                  </td>"""

replacement = """                  <!-- Actions -->
                  <td style="padding: 12px 18px; vertical-align: middle; text-align: right;">
                    <div class="d-flex justify-content-end align-items-center" style="gap: 6px;">
                      <button type="button" class="tm-btn tm-btn-ghost py-1 px-2 small" onclick="openPaymentDetails('{{ p.id }}', '{{ p.user.username }}', '{{ p.amount }}', '{{ p.currency|default:'INR' }}', '{{ p.status }}', '{{ p.payment_id|default:''|escapejs }}', '{{ p.order_id|default:''|escapejs }}', '{{ p.transaction_id|default:''|escapejs }}', '{{ p.created_at|date:'M d, Y H:i:s' }}')" title="View Full Payment Metadata">
                        <i class="fas fa-eye"></i> Details
                      </button>
                      {% if p.status == 'SUCCESS' %}
                        <button type="button" class="tm-btn tm-btn-danger py-1 px-2 small" onclick="openRefundModal('{{ p.id }}', '{{ p.amount }}', '{{ p.user.username }}')" title="Process Refund">
                          <i class="fas fa-undo-alt mr-1"></i> Refund
                        </button>
                      {% endif %}
                    </div>
                  </td>"""

if target in c:
    c = c.replace(target, replacement, 1)

modal_target = """<!-- PAYMENT DETAILS MODAL -->"""
modal_code = """<!-- REFUND MODAL -->
<div id="refundModal" style="display: none; position: fixed; inset: 0; z-index: 10000; background: rgba(0,0,0,0.85); backdrop-filter: blur(4px); align-items: center; justify-content: center; padding: 20px;">
  <div style="background: #111827; border: 1px solid #D61F45; border-radius: 12px; width: 100%; max-width: 480px; padding: 25px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h4 class="text-white font-weight-bold mb-0"><i class="fas fa-undo-alt text-danger mr-2"></i> Process Refund</h4>
      <button type="button" class="btn text-white p-0" onclick="closeRefundModal()" style="font-size: 20px;">&times;</button>
    </div>
    <form method="post" id="refundForm">
      {% csrf_token %}
      <input type="hidden" name="action" value="refund_payment">
      <input type="hidden" name="payment_id" id="refundPaymentId" value="">
      <p class="text-muted small mb-3">
        Refunding payment <strong class="text-white" id="refundModalInfo"></strong> will issue a refund via Stripe, mark the booking as CANCELLED, and immediately release reserved/booked seats.
      </p>
      <div class="form-group mb-3">
        <label class="small text-muted font-weight-bold">Reason for Refund *</label>
        <input type="text" class="form-control" name="refund_reason" placeholder="e.g. Customer cancelled / screening rescheduled" required>
      </div>
      <div class="d-flex justify-content-end" style="gap: 8px;">
        <button type="button" class="tm-btn tm-btn-ghost" onclick="closeRefundModal()">Cancel</button>
        <button type="submit" class="tm-btn tm-btn-danger"><i class="fas fa-check mr-1"></i> Confirm &amp; Process Refund</button>
      </div>
    </form>
  </div>
</div>

<script>
function openRefundModal(id, amount, user) {
  document.getElementById('refundPaymentId').value = id;
  document.getElementById('refundModalInfo').innerText = '#' + id + ' (₹' + parseFloat(amount).toFixed(2) + ' - ' + user + ')';
  document.getElementById('refundModal').style.display = 'flex';
}
function closeRefundModal() {
  document.getElementById('refundModal').style.display = 'none';
}
</script>

<!-- PAYMENT DETAILS MODAL -->"""

if modal_target in c:
    c = c.replace(modal_target, modal_code, 1)

with open('Ticketmitra/templates/admin/payments_list.html', 'w', encoding='utf-8') as f:
    f.write(c)

print("Updated payments_list.html successfully")


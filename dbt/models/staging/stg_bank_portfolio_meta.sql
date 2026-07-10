select
    pid,
    current_loan_balance,
    current_avm_value,
    avm_variance_pct,
    audit_status,
    underwriter_notes,
    resolved_model_id,
    current_loan_balance / nullif(current_avm_value, 0) as ltv
from {{ source('trident_operational', 'bank_portfolio_meta') }}

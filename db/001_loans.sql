DROP TABLE IF EXISTS loans;

CREATE TABLE loans (
    id text PRIMARY KEY,
    name text NOT NULL CONSTRAINT loans_name_length CHECK (
        char_length(name) BETWEEN 1 AND 100
    ),
    principal numeric NOT NULL
        CONSTRAINT loans_principal_positive CHECK (principal > 0)
        CONSTRAINT loans_principal_cents CHECK (scale (principal) <= 2),
    payment numeric NOT NULL
        CONSTRAINT loans_payment_positive CHECK (payment > 0)
        CONSTRAINT loans_payment_cents CHECK (scale (payment) <= 2),
    months integer NOT NULL CONSTRAINT loans_months_positive CHECK (months >= 1),
    issue_date date NOT NULL,
    first_payment_date date NOT NULL,
    day_count text NOT NULL DEFAULT 'actual'
        CONSTRAINT loans_day_count_known CHECK (day_count IN ('actual', '365')),
    weekend_shift boolean NOT NULL DEFAULT true,
    monthly_fee numeric NOT NULL DEFAULT 0.00
        CONSTRAINT loans_monthly_fee_not_negative CHECK (monthly_fee >= 0)
        CONSTRAINT loans_monthly_fee_cents CHECK (scale (monthly_fee) <= 2),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT loans_first_payment_after_issue CHECK (
        first_payment_date > issue_date
    )
);

INSERT INTO
    loans (
        id,
        name,
        principal,
        payment,
        months,
        issue_date,
        first_payment_date,
        weekend_shift
    )
VALUES (
        'teaching',
        'Credit Example',
        1200000.00,
        39857.17,
        36,
        '2026-01-15',
        '2026-02-15',
        false
    );

DROP TABLE IF EXISTS users, rate_periods, loans, payment_day_changes, prepayments;


CREATE TABLE users (
    id text NOT NULL PRIMARY KEY,
    login text NOT NULL
        CONSTRAINT users_login_unique UNIQUE
        CONSTRAINT users_login_not_empty CHECK (login <> ''),
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO users (id, login) VALUES ('u1', 'student');


CREATE TABLE loans (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users (id),
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
        user_id,
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
        'u1',
        'Credit Example',
        1200000.00,
        39857.17,
        36,
        '2026-01-15',
        '2026-02-15',
        false
    );


CREATE TABLE rate_periods (
    loan_id text NOT NULL REFERENCES loans (id),
    start_date date NOT NULL,
    annual_rate numeric NOT NULL
        CONSTRAINT rate_periods_annual_rate_not_negative CHECK (annual_rate >= 0),
    PRIMARY KEY (loan_id, start_date)
);

INSERT INTO rate_periods (loan_id, start_date, annual_rate) VALUES ('teaching', '2026-01-15', 12);


CREATE TABLE payment_day_changes (
    loan_id text NOT NULL REFERENCES loans (id),
    start_date date NOT NULL,
    day integer NOT NULL
        CONSTRAINT payment_day_changes_day_in_month CHECK (day BETWEEN 1 AND 31),
    PRIMARY KEY (loan_id, start_date)
);

CREATE TABLE prepayments (
    id text PRIMARY KEY,
    loan_id text NOT NULL REFERENCES loans (id),
    prepayment_date date NOT NULL,
    amount numeric NOT NULL
        CONSTRAINT prepayments_amount_positive CHECK (amount > 0)
        CONSTRAINT prepayments_amount_cents CHECK (scale (amount) <= 2),
    mode text NOT NULL
        CONSTRAINT prepayments_mode_known CHECK (mode IN ('reduce_term', 'reduce_payment')),
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO prepayments (id, loan_id, prepayment_date, amount, mode) VALUES ('p1', 'teaching', '2026-07-15', 200000.00, 'reduce_term');

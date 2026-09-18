-- ==========================================================
-- APEX TRUST COMMERCIAL BANK - FRAUD & SECURITY SCHEMA
-- Database: bank_fraud_portal
-- ==========================================================

-- Drop existing views and tables if they exist
DROP VIEW IF EXISTS v_customer_fraud_summary CASCADE;
DROP VIEW IF EXISTS v_fraud_tickets_full CASCADE;
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS fraud_tickets CASCADE;
DROP TABLE IF EXISTS customer_accounts CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

-- 1. Customers Table (Explicit customer_name & full_name)
CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    customer_code VARCHAR(20) UNIQUE NOT NULL,
    customer_name VARCHAR(100) NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    phone VARCHAR(25) NOT NULL,
    address VARCHAR(200),
    city VARCHAR(80),
    state VARCHAR(80),
    country VARCHAR(60) DEFAULT 'India',
    kyc_status VARCHAR(20) DEFAULT 'VERIFIED',
    risk_tier VARCHAR(20) DEFAULT 'LOW', -- LOW, MEDIUM, HIGH, CRITICAL
    account_count INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Customer Accounts Table (With customer_name column for easy pgAdmin viewing)
CREATE TABLE customer_accounts (
    account_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id) ON DELETE CASCADE,
    customer_name VARCHAR(100) NOT NULL,
    account_number VARCHAR(30) UNIQUE NOT NULL,
    account_type VARCHAR(40) NOT NULL, -- CHECKING, SAVINGS, BUSINESS, WEALTH_MANAGEMENT, CREDIT_CARD
    balance NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(5) DEFAULT 'INR',
    status VARCHAR(20) DEFAULT 'ACTIVE', -- ACTIVE, FROZEN, RESTRICTED, CLOSED
    branch VARCHAR(100) NOT NULL,
    opened_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Fraud Tickets Table (With customer_name column for easy pgAdmin viewing)
CREATE TABLE fraud_tickets (
    ticket_id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(30) UNIQUE NOT NULL,
    customer_id INT REFERENCES customers(customer_id) ON DELETE CASCADE,
    customer_name VARCHAR(100) NOT NULL,
    account_number VARCHAR(30) NOT NULL,
    incident_type VARCHAR(80) NOT NULL,
    amount_involved NUMERIC(15, 2) NOT NULL,
    recovered_amount NUMERIC(15, 2) DEFAULT 0.00,
    incident_date TIMESTAMP NOT NULL,
    reported_channel VARCHAR(40) NOT NULL,
    severity VARCHAR(20) NOT NULL, -- CRITICAL, HIGH, MEDIUM, LOW
    status VARCHAR(30) NOT NULL DEFAULT 'UNDER_INVESTIGATION', -- OPEN, UNDER_INVESTIGATION, RESOLVED, ESCALATED, FROZEN, REJECTED
    assigned_investigator VARCHAR(80) NOT NULL,
    flagged_ip_or_location VARCHAR(120),
    suspect_entity VARCHAR(150),
    description TEXT NOT NULL,
    action_taken TEXT,
    resolution_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Transactions Table (With customer_name column for easy pgAdmin viewing)
CREATE TABLE transactions (
    txn_id SERIAL PRIMARY KEY,
    txn_reference VARCHAR(40) UNIQUE NOT NULL,
    customer_id INT REFERENCES customers(customer_id) ON DELETE CASCADE,
    customer_name VARCHAR(100) NOT NULL,
    account_number VARCHAR(30) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    txn_type VARCHAR(40) NOT NULL,
    merchant_or_recipient VARCHAR(120) NOT NULL,
    channel VARCHAR(40) NOT NULL,
    ip_address VARCHAR(45),
    geo_location VARCHAR(100),
    is_fraud_flagged BOOLEAN DEFAULT FALSE,
    fraud_risk_score INT DEFAULT 15,
    status VARCHAR(30) DEFAULT 'COMPLETED',
    txn_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Audit & Security Logs (With customer_name column)
CREATE TABLE audit_logs (
    log_id SERIAL PRIMARY KEY,
    ticket_number VARCHAR(30),
    customer_name VARCHAR(100),
    actor VARCHAR(80) NOT NULL,
    action VARCHAR(80) NOT NULL,
    details TEXT NOT NULL,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_fraud_tickets_customer ON fraud_tickets(customer_id);
CREATE INDEX idx_fraud_tickets_name ON fraud_tickets(customer_name);
CREATE INDEX idx_fraud_tickets_status ON fraud_tickets(status);
CREATE INDEX idx_fraud_tickets_severity ON fraud_tickets(severity);
CREATE INDEX idx_transactions_customer ON transactions(customer_id);
CREATE INDEX idx_accounts_customer ON customer_accounts(customer_id);

-- Convenient pgAdmin Views for Instant Inspection
CREATE VIEW v_fraud_tickets_full AS
SELECT 
    t.ticket_number,
    t.customer_name,
    c.customer_code,
    c.email,
    c.phone,
    t.account_number,
    t.incident_type,
    t.amount_involved,
    t.recovered_amount,
    t.severity,
    t.status,
    t.assigned_investigator,
    t.incident_date,
    t.description
FROM fraud_tickets t
JOIN customers c ON t.customer_id = c.customer_id;

CREATE VIEW v_customer_fraud_summary AS
SELECT 
    c.customer_id,
    c.customer_code,
    c.customer_name,
    c.email,
    c.phone,
    c.risk_tier,
    ca.account_number,
    ca.account_type,
    ca.balance,
    ca.status AS account_status,
    COUNT(ft.ticket_id) AS total_fraud_tickets,
    COALESCE(SUM(ft.amount_involved), 0) AS total_fraud_amount_flagged
FROM customers c
LEFT JOIN customer_accounts ca ON c.customer_id = ca.customer_id
LEFT JOIN fraud_tickets ft ON c.customer_id = ft.customer_id
GROUP BY c.customer_id, c.customer_code, c.customer_name, c.email, c.phone, c.risk_tier, ca.account_number, ca.account_type, ca.balance, ca.status;

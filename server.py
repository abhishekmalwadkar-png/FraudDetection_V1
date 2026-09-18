"""
Dummy Bank Portal - Production Fraud Portal Backend & API Gateway
Powered by Flask & Waitress (Multi-Threaded Production WSGI Server)
Connected live to PostgreSQL (bank_fraud_portal) via PooledDB.
"""

import os
import time
import json
import uuid
import logging
from decimal import Decimal
from datetime import datetime, date, timezone
from flask import Flask, request, jsonify, send_from_directory, make_response, g
from flask.json.provider import DefaultJSONProvider
import pg8000.dbapi
import waitress

from config import (
    APP_ENV, LOG_LEVEL,
    PORTAL_HOST, PORTAL_PORT,
    DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME,
    DB_POOL_MIN_CACHED, DB_POOL_MAX_CACHED, DB_POOL_MAX_CONNECTIONS,
    SERVER_THREADS, SERVER_CONNECTION_LIMIT,
    API_SECRET_KEY, ENABLE_SQL_CONSOLE
)
from dbutils.pooled_db import PooledDB

# -------------------------------------------------------------
# Production Logging Configuration
# -------------------------------------------------------------
numeric_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(
    level=numeric_level,
    format='%(asctime)s [%(levelname)s] [Thread-%(thread)d] %(message)s'
)
logger = logging.getLogger("BankPortalServer")

# Metrics & Observability Collector
START_TIME = time.time()
METRICS = {
    "total_requests": 0,
    "total_errors": 0,
    "total_fraud_tickets_created": 0,
    "endpoints_hit": {},
    "status_codes": {}
}

# Custom JSON Provider for Flask to serialize Decimals and datetimes cleanly
class CustomFlaskJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

app = Flask(__name__, static_folder=".", static_url_path="")
app.json = CustomFlaskJSONProvider(app)

# -------------------------------------------------------------
# Database Connection Pooling (Thread-Safe Warm Pool)
# -------------------------------------------------------------
logger.info(
    f"Initializing PostgreSQL Connection Pool (min={DB_POOL_MIN_CACHED}, max={DB_POOL_MAX_CONNECTIONS}) to {DB_NAME}...",
    extra={"request_id": "INIT"}
)

def create_db_pool():
    return PooledDB(
        creator=pg8000.dbapi,
        maxconnections=DB_POOL_MAX_CONNECTIONS,
        mincached=DB_POOL_MIN_CACHED,
        maxcached=DB_POOL_MAX_CACHED,
        maxshared=0,
        blocking=True,
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME
    )

db_pool = create_db_pool()
logger.info("[+] PostgreSQL Connection Pool is ready and active.", extra={"request_id": "INIT"})

def get_db_connection(max_retries=2):
    """Retrieve an active, pre-connected PostgreSQL socket with automatic reconnection resilience."""
    last_err = None
    for attempt in range(max_retries):
        try:
            return db_pool.connection()
        except Exception as e:
            last_err = e
            logger.warning(f"Connection pool acquisition retry {attempt+1}/{max_retries}: {e}", extra={"request_id": getattr(g, "request_id", "SYS")})
            time.sleep(0.1)
    raise RuntimeError(f"Database connection pool exhausted or unreachable: {last_err}")

# -------------------------------------------------------------
# Middleware: Request Tracing, Latency & Access Logging
# -------------------------------------------------------------
@app.before_request
def before_request_hook():
    g.start_time = time.time()
    # Read incoming request ID or generate a new trace UUID
    req_id = request.headers.get("X-Request-ID") or f"REQ-{uuid.uuid4().hex[:12].upper()}"
    g.request_id = req_id
    
    # Update global metrics
    METRICS["total_requests"] += 1
    endpoint = request.endpoint or request.path
    METRICS["endpoints_hit"][endpoint] = METRICS["endpoints_hit"].get(endpoint, 0) + 1

@app.after_request
def after_request_hook(response):
    req_id = getattr(g, "request_id", "UNKNOWN")
    response.headers['X-Request-ID'] = req_id
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-API-Key, X-Request-ID'
    
    # Calculate duration
    duration_ms = (time.time() - getattr(g, "start_time", time.time())) * 1000.0
    status = response.status_code
    METRICS["status_codes"][status] = METRICS["status_codes"].get(status, 0) + 1
    
    if status >= 400:
        METRICS["total_errors"] += 1
        logger.warning(
            f"{request.method} {request.path} {status} - {duration_ms:.2f}ms - IP: {request.remote_addr}",
            extra={"request_id": req_id}
        )
    else:
        logger.info(
            f"{request.method} {request.path} {status} - {duration_ms:.2f}ms - IP: {request.remote_addr}",
            extra={"request_id": req_id}
        )
    return response

# Handle OPTIONS preflight globally
@app.route('/<path:dummy>', methods=['OPTIONS'])
@app.route('/', methods=['OPTIONS'])
def handle_options(dummy=None):
    return make_response('', 200)

# -------------------------------------------------------------
# Centralized JSON Error Handlers
# -------------------------------------------------------------
@app.errorhandler(400)
def error_bad_request(e):
    return jsonify({
        "error": "Bad Request",
        "message": str(getattr(e, "description", e)),
        "request_id": getattr(g, "request_id", "UNKNOWN"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 400

@app.errorhandler(401)
def error_unauthorized(e):
    return jsonify({
        "error": "Unauthorized",
        "message": "Valid API Key or Bearer token is required.",
        "request_id": getattr(g, "request_id", "UNKNOWN"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 401

@app.errorhandler(403)
def error_forbidden(e):
    return jsonify({
        "error": "Forbidden",
        "message": str(getattr(e, "description", "Action is forbidden.")),
        "request_id": getattr(g, "request_id", "UNKNOWN"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 403

@app.errorhandler(404)
def error_not_found(e):
    return jsonify({
        "error": "Not Found",
        "message": "The requested resource was not found on this server.",
        "request_id": getattr(g, "request_id", "UNKNOWN"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 404

@app.errorhandler(405)
def error_method_not_allowed(e):
    return jsonify({
        "error": "Method Not Allowed",
        "message": "The HTTP method is not supported for this endpoint.",
        "request_id": getattr(g, "request_id", "UNKNOWN"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 405

@app.errorhandler(500)
def error_internal_server(e):
    req_id = getattr(g, "request_id", "UNKNOWN")
    logger.error(f"Internal Server Error: {e}", exc_info=True, extra={"request_id": req_id})
    return jsonify({
        "error": "Internal Server Error",
        "message": "An unexpected server error occurred. Please contact the SOC operations team.",
        "request_id": req_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 500

# -------------------------------------------------------------
# Security & Helper Functions
# -------------------------------------------------------------
def check_api_auth():
    """Verify API authentication if API_SECRET_KEY is configured in .env."""
    if not API_SECRET_KEY:
        return True  # Open local dev mode
    
    # Check X-API-Key header or Authorization: Bearer <key>
    auth_header = request.headers.get("Authorization", "")
    api_key_header = request.headers.get("X-API-Key", "")
    
    if api_key_header and api_key_header == API_SECRET_KEY:
        return True
    if auth_header.startswith("Bearer ") and auth_header.split(" ", 1)[1].strip() == API_SECRET_KEY:
        return True
    return False

def _get_val(payload, *keys, default=None):
    """Helper function to extract fields flexibly regardless of casing/naming."""
    if not isinstance(payload, dict):
        return default
    # Direct lookup
    for k in keys:
        if k in payload and payload[k] not in (None, "", "null", "<null>"):
            return payload[k]
    # Case-insensitive / normalized lookup
    norm_map = {str(k).lower().replace("_", "").replace("-", "").replace(" ", ""): v for k, v in payload.items()}
    for k in keys:
        norm_k = k.lower().replace("_", "").replace("-", "").replace(" ", "")
        if norm_k in norm_map and norm_map[norm_k] not in (None, "", "null", "<null>"):
            return norm_map[norm_k]
    return default

def parse_incoming_payload():
    """Parse JSON or Form or Query params safely from request."""
    payload = {}
    if request.is_json:
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
    elif request.form:
        payload = request.form.to_dict()
    else:
        # Check raw data
        raw = request.get_data(as_text=True)
        if raw and raw.strip() and raw.strip() != "[object Object]":
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                pass
    # Merge query params if payload missing keys
    if request.args:
        for k, v in request.args.items():
            if k not in payload or not payload[k]:
                payload[k] = v
    return payload

# -------------------------------------------------------------
# Static Frontend Routes
# -------------------------------------------------------------
@app.route('/')
def serve_index():
    return send_from_directory(".", "index.html")

@app.route('/styles.css')
def serve_css():
    return send_from_directory(".", "styles.css")

@app.route('/app.js')
def serve_js():
    return send_from_directory(".", "app.js")

@app.route('/health')
def health_check():
    """Enterprise Health Check with Live PostgreSQL Ping & Pool Latency."""
    t0 = time.time()
    db_ok = False
    db_latency_ms = 0.0
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        cur.close()
        conn.close()
        db_ok = True
        db_latency_ms = round((time.time() - t0) * 1000.0, 2)
    except Exception as e:
        logger.error(f"Health check DB ping failed: {e}", extra={"request_id": getattr(g, "request_id", "HEALTH")})

    return jsonify({
        "status": "UP" if db_ok else "DEGRADED",
        "environment": APP_ENV,
        "server": "Waitress (Production WSGI)",
        "worker_threads": SERVER_THREADS,
        "database": {
            "status": "CONNECTED" if db_ok else "DISCONNECTED",
            "ping_latency_ms": db_latency_ms,
            "pool": {
                "type": "DBUtils.PooledDB",
                "min_cached": DB_POOL_MIN_CACHED,
                "max_cached": DB_POOL_MAX_CACHED,
                "max_connections": DB_POOL_MAX_CONNECTIONS,
                "database": DB_NAME
            }
        },
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

@app.route('/api/metrics')
def api_metrics():
    """Observability & Telemetry Endpoint for System Monitoring."""
    uptime = time.time() - START_TIME
    return jsonify({
        "uptime_seconds": round(uptime, 2),
        "total_requests": METRICS["total_requests"],
        "total_errors": METRICS["total_errors"],
        "error_rate": round(METRICS["total_errors"] / max(1, METRICS["total_requests"]), 4),
        "total_fraud_tickets_created": METRICS["total_fraud_tickets_created"],
        "endpoints_hit": METRICS["endpoints_hit"],
        "status_codes": METRICS["status_codes"],
        "server": {
            "threads": SERVER_THREADS,
            "max_connections": SERVER_CONNECTION_LIMIT
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------
@app.route('/api/overview', methods=['GET'])
def api_overview():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM fraud_tickets;")
        total_tickets = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(amount_involved), 0) FROM fraud_tickets;")
        total_amount = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(recovered_amount), 0) FROM fraud_tickets;")
        recovered_amount = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status = 'UNDER_INVESTIGATION';")
        under_investigation = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status = 'FROZEN';")
        frozen_accounts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_tickets WHERE status = 'RESOLVED';")
        resolved_cases = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM customers WHERE risk_tier = 'CRITICAL';")
        critical_customers = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM customers;")
        total_customers = cursor.fetchone()[0]

        return jsonify({
            "total_tickets": total_tickets,
            "total_amount": float(total_amount),
            "recovered_amount": float(recovered_amount),
            "under_investigation": under_investigation,
            "frozen_accounts": frozen_accounts,
            "resolved_cases": resolved_cases,
            "critical_customers": critical_customers,
            "total_customers": total_customers
        })
    finally:
        cursor.close()
        conn.close()

@app.route('/api/fraud-tickets', methods=['GET'])
def api_get_fraud_tickets():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        sql = """
            SELECT 
                t.ticket_id, t.ticket_number, t.customer_id, c.customer_code, c.full_name, c.email, c.phone, c.risk_tier,
                t.account_number, ca.account_type, ca.balance, ca.status as account_status,
                t.incident_type, t.amount_involved, t.recovered_amount, t.incident_date,
                t.reported_channel, t.severity, t.status, t.assigned_investigator,
                t.flagged_ip_or_location, t.suspect_entity, t.description, t.action_taken,
                t.created_at
            FROM fraud_tickets t
            JOIN customers c ON t.customer_id = c.customer_id
            LEFT JOIN customer_accounts ca ON (t.customer_id = ca.customer_id AND t.account_number = ca.account_number)
            ORDER BY t.ticket_id DESC;
        """
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        tickets = []
        for r in rows:
            tickets.append({
                "ticket_id": r[0],
                "ticket_number": r[1],
                "customer_id": r[2],
                "customer_code": r[3],
                "customer_name": r[4],
                "full_name": r[4],
                "email": r[5],
                "phone": r[6],
                "risk_tier": r[7],
                "account_number": r[8],
                "account_type": r[9],
                "balance": float(r[10]) if r[10] is not None else 0.0,
                "account_status": r[11] or 'ACTIVE',
                "incident_type": r[12],
                "amount_involved": float(r[13]),
                "recovered_amount": float(r[14]),
                "incident_date": r[15],
                "reported_channel": r[16],
                "severity": r[17],
                "status": r[18],
                "assigned_investigator": r[19],
                "flagged_ip_or_location": r[20],
                "suspect_entity": r[21],
                "description": r[22],
                "action_taken": r[23],
                "created_at": r[24]
            })
        return jsonify(tickets)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/fraud-tickets/<ticket_id>', methods=['GET'])
def api_get_single_ticket(ticket_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 
                t.ticket_id, t.ticket_number, t.customer_id, c.customer_code, c.full_name, c.email, c.phone, c.risk_tier,
                c.address, c.city, c.state,
                t.account_number, ca.account_type, ca.balance, ca.status as account_status, ca.branch,
                t.incident_type, t.amount_involved, t.recovered_amount, t.incident_date,
                t.reported_channel, t.severity, t.status, t.assigned_investigator,
                t.flagged_ip_or_location, t.suspect_entity, t.description, t.action_taken,
                t.created_at
            FROM fraud_tickets t
            JOIN customers c ON t.customer_id = c.customer_id
            LEFT JOIN customer_accounts ca ON (t.customer_id = ca.customer_id AND t.account_number = ca.account_number)
            WHERE t.ticket_id = %s OR t.ticket_number = %s;
        """, (int(ticket_id) if ticket_id.isdigit() else -1, ticket_id))
        r = cursor.fetchone()

        if not r:
            return jsonify({"error": "Ticket not found"}), 404

        ticket = {
            "ticket_id": r[0],
            "ticket_number": r[1],
            "customer_id": r[2],
            "customer_code": r[3],
            "full_name": r[4],
            "customer_name": r[4],
            "email": r[5],
            "phone": r[6],
            "risk_tier": r[7],
            "address": r[8],
            "city": r[9],
            "state": r[10],
            "account_number": r[11],
            "account_type": r[12],
            "balance": float(r[13]) if r[13] is not None else 0.0,
            "account_status": r[14] or 'ACTIVE',
            "branch": r[15],
            "incident_type": r[16],
            "amount_involved": float(r[17]),
            "recovered_amount": float(r[18]),
            "incident_date": r[19],
            "reported_channel": r[20],
            "severity": r[21],
            "status": r[22],
            "assigned_investigator": r[23],
            "flagged_ip_or_location": r[24],
            "suspect_entity": r[25],
            "description": r[26],
            "action_taken": r[27],
            "created_at": r[28]
        }

        # Get linked transactions
        cursor.execute("""
            SELECT txn_id, txn_reference, amount, txn_type, merchant_or_recipient, channel, ip_address, is_fraud_flagged, fraud_risk_score, status, txn_time
            FROM transactions
            WHERE customer_id = %s
            ORDER BY txn_id DESC;
        """, (ticket["customer_id"],))
        txns = []
        for t in cursor.fetchall():
            txns.append({
                "txn_id": t[0], "txn_reference": t[1], "amount": float(t[2]), "txn_type": t[3],
                "merchant_or_recipient": t[4], "channel": t[5], "ip_address": t[6],
                "is_fraud_flagged": t[7], "fraud_risk_score": t[8], "status": t[9], "txn_time": t[10]
            })
        ticket["transactions"] = txns

        # Get audit logs
        cursor.execute("""
            SELECT log_id, actor, action, details, ip_address, created_at
            FROM audit_logs
            WHERE ticket_number = %s
            ORDER BY log_id DESC;
        """, (ticket["ticket_number"],))
        logs = []
        for l in cursor.fetchall():
            logs.append({
                "log_id": l[0], "actor": l[1], "action": l[2], "details": l[3], "ip_address": l[4], "created_at": l[5]
            })
        ticket["audit_logs"] = logs

        return jsonify(ticket)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/fraud-tickets', methods=['POST'])
def api_create_fraud_ticket():
    # Verify API authorization if configured
    if not check_api_auth():
        return jsonify({"error": "Unauthorized", "message": "Invalid or missing API key."}), 401

    raw_body = request.get_data(as_text=True)
    payload = parse_incoming_payload()

    if (not payload or len(payload) == 0) and "[object Object]" in raw_body:
        return jsonify({
            "success": False,
            "error": "Received '[object Object]' as request body. In Process Studio, please use 'JSON.stringify(data)' to format your body field as a valid JSON string before sending."
        }), 400

    # Field extraction & input validation
    cust_name = str(_get_val(payload, "full_name", "customer_name", "fullname", "name", "cust_name", default="Ramesh Kumar")).strip()
    if not cust_name:
        return jsonify({"success": False, "error": "Customer full_name cannot be blank."}), 400

    email = str(_get_val(payload, "email", "mail", default=f"{cust_name.lower().replace(' ', '')}_{datetime.now().strftime('%M%S')}@example.com")).strip()
    phone = str(_get_val(payload, "phone", "mobile", "contact", default="+91 98765 00000")).strip()
    
    severity = str(_get_val(payload, "severity", "risk_tier", "priority", default="HIGH")).upper().strip()
    if severity not in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
        severity = "HIGH"
    risk_tier = severity
    
    cust_code = f"CUST-{uuid.uuid4().hex[:6].upper()}"
    acc_num = str(_get_val(payload, "account_number", "account_no", "accountnumber", "acc_num", default=f"ACT-{uuid.uuid4().hex[:6].upper()}")).strip()
    acc_type = str(_get_val(payload, "account_type", "accounttype", default="SAVINGS")).upper().strip()
    
    raw_amount = _get_val(payload, "amount_involved", "amount", "amountinvolved", default="25000")
    try:
        amount = float(str(raw_amount).replace(",", "").replace("₹", "").strip())
        if amount <= 0:
            return jsonify({"success": False, "error": "amount_involved must be greater than zero."}), 400
    except ValueError:
        return jsonify({"success": False, "error": f"Invalid numerical amount_involved: '{raw_amount}'"}), 400

    incident_type = str(_get_val(payload, "incident_type", "incidenttype", "fraud_type", default="Fake QR Code Scam")).strip()
    channel = str(_get_val(payload, "reported_channel", "channel", default="Customer Help Desk")).strip()
    desc = str(_get_val(payload, "description", "desc", "details", default="Customer submitted fraud report.")).strip()
    suspect = str(_get_val(payload, "suspect_entity", "suspect", "merchant", default="Unknown Merchant UPI")).strip()
    flagged_ip = str(_get_val(payload, "flagged_ip_or_location", "location", "ip_address", default="Web Client Terminal")).strip()
    ticket_num = f"FRD-2026-{uuid.uuid4().hex[:8].upper()}"

    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        # 1. Check if customer already exists
        cursor.execute("""
            SELECT customer_id, full_name, risk_tier 
            FROM customers 
            WHERE email = %s OR phone = %s OR full_name = %s 
            ORDER BY customer_id ASC 
            LIMIT 1;
        """, (email, phone, cust_name))
        existing_cust = cursor.fetchone()

        if existing_cust:
            cust_id = existing_cust[0]
            cursor.execute("""
                UPDATE customers 
                SET full_name = %s, customer_name = %s, email = %s, phone = %s, risk_tier = %s 
                WHERE customer_id = %s;
            """, (cust_name, cust_name, email, phone, risk_tier, cust_id))
            cursor.execute("""
                UPDATE customer_accounts
                SET customer_name = %s
                WHERE customer_id = %s;
            """, (cust_name, cust_id))
        else:
            cursor.execute("""
                INSERT INTO customers (customer_code, customer_name, full_name, email, phone, risk_tier)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING customer_id;
            """, (cust_code, cust_name, cust_name, email, phone, risk_tier))
            cust_id = cursor.fetchone()[0]

        # 2. Check if account already exists
        cursor.execute("SELECT account_id FROM customer_accounts WHERE account_number = %s LIMIT 1;", (acc_num,))
        existing_acc = cursor.fetchone()
        if not existing_acc:
            cursor.execute("""
                INSERT INTO customer_accounts (customer_id, customer_name, account_number, account_type, balance, branch, opened_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (cust_id, cust_name, acc_num, acc_type, amount, "Mumbai Branch", "2024-01-01"))

        # 3. Insert fraud ticket
        cursor.execute("""
            INSERT INTO fraud_tickets (
                ticket_number, customer_id, customer_name, account_number, incident_type,
                amount_involved, recovered_amount, incident_date, reported_channel,
                severity, status, assigned_investigator, flagged_ip_or_location,
                suspect_entity, description, action_taken
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING ticket_id;
        """, (
            ticket_num, cust_id, cust_name, acc_num, incident_type,
            amount, 0.0, datetime.now(), channel,
            severity, "UNDER_INVESTIGATION", "Shreya Deshmukh (Support Lead)",
            flagged_ip, suspect,
            desc, "Complaint logged into PostgreSQL database; Assigned to Support Team."
        ))
        new_ticket_id = cursor.fetchone()[0]

        # 4. Audit log
        cursor.execute("""
            INSERT INTO audit_logs (ticket_number, customer_name, actor, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (ticket_num, cust_name, "Process Studio RPA Intake", "NEW_INCIDENT_REGISTERED", f"Created fraud ticket {ticket_num} for {cust_name} ({incident_type} - ₹{amount:,.2f})", request.remote_addr or "127.0.0.1"))

        conn.commit()
        METRICS["total_fraud_tickets_created"] += 1

        return jsonify({
            "success": True, 
            "ticket_id": new_ticket_id, 
            "ticket_number": ticket_num, 
            "customer_name": cust_name, 
            "account_number": acc_num,
            "incident_type": incident_type,
            "amount_involved": amount
        }), 201
    except Exception as ex:
        logger.error(f"Error creating fraud ticket: {ex}", exc_info=True, extra={"request_id": getattr(g, "request_id", "SYS")})
        return jsonify({"success": False, "error": str(ex)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/fraud-tickets/<ticket_id>', methods=['PATCH'])
def api_update_ticket(ticket_id):
    payload = parse_incoming_payload()
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        status = payload.get("status")
        if status and status not in ["UNDER_INVESTIGATION", "FROZEN", "RESOLVED", "CLOSED", "REJECTED"]:
            return jsonify({"error": f"Invalid status: '{status}'"}), 400

        action_note = payload.get("action_taken", "")

        cursor.execute("""
            UPDATE fraud_tickets
            SET status = COALESCE(%s, status),
                action_taken = CASE WHEN %s != '' THEN %s ELSE action_taken END,
                updated_at = CURRENT_TIMESTAMP
            WHERE ticket_id = %s OR ticket_number = %s
            RETURNING ticket_number, customer_id, account_number;
        """, (status, action_note, action_note, int(ticket_id) if ticket_id.isdigit() else -1, ticket_id))
        res = cursor.fetchone()

        if not res:
            return jsonify({"error": "Ticket not found"}), 404

        ticket_num, cust_id, acc_num = res

        # If status was updated to FROZEN, freeze the account too
        if status == "FROZEN":
            cursor.execute("UPDATE customer_accounts SET status = 'FROZEN' WHERE customer_id = %s;", (cust_id,))

        # Audit log
        cursor.execute("""
            INSERT INTO audit_logs (ticket_number, actor, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s);
        """, (ticket_num, "SOC Lead Investigator", f"STATUS_{status}", f"Updated status to {status}. Note: {action_note}", request.remote_addr or "127.0.0.1"))

        conn.commit()
        return jsonify({"success": True, "ticket_number": ticket_num, "status": status})
    finally:
        cursor.close()
        conn.close()

@app.route('/api/freeze-account', methods=['POST'])
def api_freeze_account():
    payload = parse_incoming_payload()
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        acc_num = payload.get("account_number")
        ticket_num = payload.get("ticket_number")

        if not acc_num:
            return jsonify({"error": "account_number is required"}), 400

        cursor.execute("UPDATE customer_accounts SET status = 'FROZEN' WHERE account_number = %s;", (acc_num,))
        if ticket_num:
            cursor.execute("UPDATE fraud_tickets SET status = 'FROZEN' WHERE ticket_number = %s;", (ticket_num,))

        cursor.execute("""
            INSERT INTO audit_logs (ticket_number, actor, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s);
        """, (ticket_num or "MANUAL_LOCK", "SOC Security Officer", "ACCOUNT_EMERGENCY_FREEZE", f"Account {acc_num} frozen due to fraud risk", request.remote_addr or "127.0.0.1"))

        conn.commit()
        return jsonify({"success": True, "account_number": acc_num, "status": "FROZEN"})
    finally:
        cursor.close()
        conn.close()

@app.route('/api/customers', methods=['GET'])
def api_get_customers():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 
                c.customer_id, c.customer_code, c.full_name, c.email, c.phone, c.city, c.state, c.risk_tier,
                ca.account_number, ca.account_type, ca.balance, ca.status as account_status, ca.branch,
                COUNT(ft.ticket_id) as fraud_reports_count
            FROM customers c
            LEFT JOIN customer_accounts ca ON c.customer_id = ca.customer_id
            LEFT JOIN fraud_tickets ft ON c.customer_id = ft.customer_id
            GROUP BY c.customer_id, c.customer_code, c.full_name, c.email, c.phone, c.city, c.state, c.risk_tier,
                     ca.account_number, ca.account_type, ca.balance, ca.status, ca.branch
            ORDER BY c.customer_id ASC;
        """)
        rows = cursor.fetchall()
        customers = []
        for r in rows:
            customers.append({
                "customer_id": r[0], "customer_code": r[1], "full_name": r[2], "email": r[3],
                "phone": r[4], "city": r[5], "state": r[6], "risk_tier": r[7],
                "account_number": r[8], "account_type": r[9],
                "balance": float(r[10]) if r[10] is not None else 0.0,
                "account_status": r[11] or 'ACTIVE', "branch": r[12],
                "fraud_reports_count": r[13]
            })
        return jsonify(customers)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/transactions', methods=['GET'])
def api_get_transactions():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 
                t.txn_id, t.txn_reference, t.customer_id, c.full_name, t.account_number,
                t.amount, t.txn_type, t.merchant_or_recipient, t.channel, t.ip_address,
                t.is_fraud_flagged, t.fraud_risk_score, t.status, t.txn_time
            FROM transactions t
            JOIN customers c ON t.customer_id = c.customer_id
            ORDER BY t.txn_id DESC;
        """)
        rows = cursor.fetchall()
        txns = []
        for r in rows:
            txns.append({
                "txn_id": r[0], "txn_reference": r[1], "customer_id": r[2], "full_name": r[3],
                "account_number": r[4], "amount": float(r[5]), "txn_type": r[6],
                "merchant_or_recipient": r[7], "channel": r[8], "ip_address": r[9],
                "is_fraud_flagged": r[10], "fraud_risk_score": r[11], "status": r[12],
                "txn_time": r[13]
            })
        return jsonify(txns)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/analytics', methods=['GET'])
def api_get_analytics():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT incident_type, COUNT(*), SUM(amount_involved)
            FROM fraud_tickets
            GROUP BY incident_type
            ORDER BY COUNT(*) DESC;
        """)
        by_type = [{"type": r[0], "count": r[1], "amount": float(r[2])} for r in cursor.fetchall()]

        cursor.execute("""
            SELECT reported_channel, COUNT(*), SUM(amount_involved)
            FROM fraud_tickets
            GROUP BY reported_channel
            ORDER BY COUNT(*) DESC;
        """)
        by_channel = [{"channel": r[0], "count": r[1], "amount": float(r[2])} for r in cursor.fetchall()]

        cursor.execute("""
            SELECT severity, COUNT(*)
            FROM fraud_tickets
            GROUP BY severity;
        """)
        by_severity = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute("""
            SELECT status, COUNT(*)
            FROM fraud_tickets
            GROUP BY status;
        """)
        by_status = {r[0]: r[1] for r in cursor.fetchall()}

        return jsonify({
            "by_type": by_type,
            "by_channel": by_channel,
            "by_severity": by_severity,
            "by_status": by_status
        })
    finally:
        cursor.close()
        conn.close()

@app.route('/api/audit-logs', methods=['GET'])
def api_get_audit_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT log_id, ticket_number, actor, action, details, ip_address, created_at
            FROM audit_logs
            ORDER BY log_id DESC
            LIMIT 100;
        """)
        logs = []
        for r in cursor.fetchall():
            logs.append({
                "log_id": r[0], "ticket_number": r[1], "actor": r[2], "action": r[3],
                "details": r[4], "ip_address": r[5], "created_at": r[6]
            })
        return jsonify(logs)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/db-status', methods=['GET'])
def api_get_db_status():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT version();")
        pg_ver = cursor.fetchone()[0]

        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """)
        tables = [r[0] for r in cursor.fetchall()]

        table_counts = {}
        for tbl in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {tbl};")
            table_counts[tbl] = cursor.fetchone()[0]

        return jsonify({
            "connected": True,
            "database": DB_NAME,
            "host": DB_HOST,
            "port": DB_PORT,
            "user": DB_USER,
            "pgAdmin_info": f"Connected to PostgreSQL on port {DB_PORT} as {DB_USER}. Visible in pgAdmin 4 under Databases > {DB_NAME}.",
            "version": pg_ver,
            "tables": tables,
            "counts": table_counts
        })
    finally:
        cursor.close()
        conn.close()

@app.route('/api/execute-sql', methods=['POST'])
def api_execute_sql():
    if not ENABLE_SQL_CONSOLE:
        return jsonify({"error": "SQL Console is disabled in this environment."}), 403

    payload = parse_incoming_payload()
    query = payload.get("query", "").strip()
    if not query:
        return jsonify({"error": "Empty SQL query"}), 400

    # In production mode, guard against accidental DROP / TRUNCATE unless authorized
    if APP_ENV == "production" and not check_api_auth():
        upper_q = query.upper()
        if any(keyword in upper_q for keyword in ["DROP DATABASE", "DROP TABLE", "TRUNCATE"]):
            return jsonify({"error": "Destructive DDL statements are blocked in production mode."}), 403

    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        cursor.execute(query)
        if cursor.description:
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            formatted_rows = []
            for row in rows:
                formatted_rows.append([float(c) if isinstance(c, Decimal) else (c.isoformat() if isinstance(c, (datetime, date)) else c) for c in row])
            return jsonify({
                "success": True,
                "columns": columns,
                "rows": formatted_rows,
                "row_count": len(rows)
            })
        else:
            return jsonify({
                "success": True,
                "message": "Query executed successfully. (No returning rows)",
                "row_count": cursor.rowcount
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        cursor.close()
        conn.close()

# -------------------------------------------------------------
# Production Server Entry Point
# -------------------------------------------------------------
def run_production_server():
    print("=" * 75)
    print("  DUMMY BANK PORTAL - ENTERPRISE FRAUD SYSTEM")
    print("  Production WSGI Server: Waitress")
    print(f"  Environment: {APP_ENV.upper()}")
    print(f"  Host: http://{PORTAL_HOST}:{PORTAL_PORT}")
    print(f"  Worker Threads: {SERVER_THREADS} Concurrent Workers")
    print(f"  Connection Limit: {SERVER_CONNECTION_LIMIT} Sockets")
    print(f"  Database: PostgreSQL ({DB_NAME}) on port {DB_PORT}")
    print("=" * 75)
    
    waitress.serve(
        app,
        host=PORTAL_HOST,
        port=PORTAL_PORT,
        threads=SERVER_THREADS,
        connection_limit=SERVER_CONNECTION_LIMIT,
        channel_timeout=30,
        ident="DummyBankPortal-WSGI/1.0"
    )

if __name__ == "__main__":
    run_production_server()

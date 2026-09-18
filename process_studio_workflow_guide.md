# Process Studio Workflow Guide: Reporting New Fraud Complaints

This guide provides step-by-step instructions on how to create a workflow in **Process Studio (AutomationEdge RPA)** that sends new fraud complaint data directly to the PostgreSQL database (`bank_fraud_portal`) or via the Bank Portal REST API, so it immediately reflects on the Bank Portal UI.

---

## Architecture & Data Flow

```
[ Input Source ] (Email, Excel, Helpdesk Form, or Webhook)
       │
       ▼
[ Process Studio Workflow ] (Extracts Customer Details & Fraud Incident)
       │
       ├──► Option 1: Direct Database Step ("Table Output" -> PostgreSQL `bank_fraud_portal`)
       │                         OR
       └──► Option 2: REST Client Step (POST `http://localhost:5050/api/fraud-tickets`)
                                 │
                                 ▼
                     [ PostgreSQL Database ]
                                 │
                                 ▼
                    [ Bank Portal Web UI ] (Live Reflected)
```

---

## Method 1: Direct PostgreSQL Database Insert (Recommended in Process Studio)

### Step 1: Configure Database Connection in Process Studio
1. In Process Studio, open your workflow or create a new one (**File > New > Workflow/Process**).
2. In the left panel, right-click **Database connections** > **New**.
3. Fill in the connection parameters (as configured in your `.env`):
   - **Connection Name**: `PG_Bank_Fraud_DB`
   - **Connection Type**: `PostgreSQL`
   - **Host Name**: `localhost` (or `127.0.0.1`)
   - **Database Name**: `bank_fraud_portal`
   - **Port Number**: `5432`
   - **User Name**: `postgres`
   - **Password**: `<YOUR_DB_PASSWORD>` (as configured in `.env`)
4. Click **Test** to ensure connection is successful (`Connection to database [PG_Bank_Fraud_DB] OK`).
5. Click **OK** to save.

---

### Step 2: Build the Workflow Steps

#### 1. Input Step (`Data Grid`, `Excel Input`, or `CSV file input`)
- Add your input source step containing customer fraud report fields:
  - `full_name` (String) - e.g., `"Manoj Kumar"`
  - `email` (String) - e.g., `"manoj.k@example.in"`
  - `phone` (String) - e.g., `"+91 98110 55443"`
  - `account_number` (String) - e.g., `"ACT-9911-3322"`
  - `account_type` (String) - e.g., `"SAVINGS"`
  - `incident_type` (String) - e.g., `"Unauthorized Bank Transfer"`
  - `amount_involved` (Number) - e.g., `45000.00`
  - `severity` (String) - e.g., `"HIGH"`
  - `description` (String) - e.g., `"Customer reported unauthorized online transfer."`

---

#### 2. Generate Unique IDs & Timestamps (`Modified Java Script Value` or `Generate random value`)
Add a **Modified JavaScript Value** step to generate ticket number and timestamps:
```javascript
// Generate dynamic Complaint / Ticket Number
var ticket_number = "FRD-2026-" + Math.floor(1000 + Math.random() * 9000);
var customer_code = "CUST-" + Math.floor(10000 + Math.random() * 90000);
var incident_date = new Date();
var status = "UNDER_INVESTIGATION";
var reported_channel = "Process Studio RPA Bot";
var assigned_investigator = "Shreya Deshmukh (Support Lead)";
```

---

#### 3. Insert into `customers` Table (`Table Output` Step)
- Drag a **Table Output** step named `Insert Customer`.
- **Connection**: `PG_Bank_Fraud_DB`
- **Target Table**: `customers`
- Check **Specify database fields**.
- Map fields in **Database fields**:
  - `customer_code` -> `customer_code`
  - `customer_name` -> `full_name`
  - `full_name` -> `full_name`
  - `email` -> `email`
  - `phone` -> `phone`
  - `risk_tier` -> `severity`
- In **Return auto-generated key**, check the box and set **Name of auto-generated key field** to `customer_id`.

---

#### 4. Insert into `customer_accounts` Table (`Table Output` Step)
- Drag a **Table Output** step named `Insert Account`.
- **Target Table**: `customer_accounts`
- Map:
  - `customer_id` -> `customer_id`
  - `customer_name` -> `full_name`
  - `account_number` -> `account_number`
  - `account_type` -> `account_type`
  - `balance` -> `50000.00` (or input balance)
  - `branch` -> `"Main Branch"`

---

#### 5. Insert into `fraud_tickets` Table (`Table Output` Step)
- Drag a **Table Output** step named `Insert Fraud Ticket`.
- **Target Table**: `fraud_tickets`
- Map:
  - `ticket_number` -> `ticket_number`
  - `customer_id` -> `customer_id`
  - `customer_name` -> `full_name`
  - `account_number` -> `account_number`
  - `incident_type` -> `incident_type`
  - `amount_involved` -> `amount_involved`
  - `recovered_amount` -> `0.00`
  - `severity` -> `severity`
  - `status` -> `status`
  - `reported_channel` -> `reported_channel`
  - `assigned_investigator` -> `assigned_investigator`
  - `description` -> `description`
  - `action_taken` -> `"Ticket registered by RPA automation bot."`

---

#### 6. Insert into `audit_logs` Table (`Table Output` Step)
- **Target Table**: `audit_logs`
- Map:
  - `ticket_number` -> `ticket_number`
  - `customer_name` -> `full_name`
  - `actor` -> `"AutomationEdge RPA Bot"`
  - `action` -> `"NEW_COMPLAINT_AUTOMATED"`
  - `details` -> `"Automated intake of fraud complaint from external channel."`

---

## Method 2: REST Client API Step (Simplest Method)

If you prefer sending an API request from Process Studio instead of individual table steps:

### Step-by-Step Configuration:

1. **Step 1: Input Step (`Data Grid` or `Excel Input`)**
   - Provide the fraud columns: `full_name`, `email`, `phone`, `account_number`, `account_type`, `incident_type`, `amount_involved`, `severity`, `suspect_entity`, `description`.

2. **Step 2: Format as JSON String (`Modified Java Script Value` Step)**
   - In Process Studio, when passing fields into the REST Client body, create a JSON string so it is not sent as raw object:
     ```javascript
     // Build JSON Payload String
     var request_body = JSON.stringify({
       "full_name": full_name,
       "email": email,
       "phone": String(phone),
       "account_number": String(account_number),
       "account_type": account_type,
       "incident_type": incident_type,
       "amount_involved": Number(amount_involved),
       "severity": severity,
       "suspect_entity": suspect_entity,
       "description": description
     });
     ```

3. **Step 3: REST Client (or Arc Client) Step**
   - **URL field**: `http://localhost:5050/api/fraud-tickets`
   - **HTTP Method**: `POST`
   - **Body field / Request entity field**: Select `request_body` (the JSON string created in step 2)
   - **Headers**:
     - `Content-Type`: `application/json`
   - **Result field name**: `ArcRespBody`
   - **HTTP status code field**: `ArcRespCode`

4. Click **Run**. The server automatically creates the customer, account, ticket, and audit log in PostgreSQL and returns `201 Created`.

---

## How It Reflects on the Bank Portal UI

Once your Process Studio workflow executes:
1. The record is committed into the **`bank_fraud_portal`** database in PostgreSQL.
2. Open or switch to the Bank Portal at **[http://127.0.0.1:5050](http://127.0.0.1:5050)**.
3. Click the **"Refresh"** button at the top (or switch tabs).
4. **Immediate Visibility**:
   - The new customer name and complaint ID appear instantly at the top of the **Fraud Complaints** table.
   - The Top KPI ribbons (**Total Customers**, **Fraud Complaints**, **Total Money Reported**) increase automatically.
   - Clicking **"View Details"** opens the full customer summary with transaction details.
   - The complaint is immediately visible in **pgAdmin 4** under `fraud_tickets` and `customers`.

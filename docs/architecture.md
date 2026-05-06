# MachineWhisperer — Architecture & Technical Design

## 1. High-Level Block Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MACHINEWHISPERER SYSTEM                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────┐     ┌──────────────────┐     ┌───────────────────────┐  │
│   │   SIMULATOR  │     │     BACKEND       │     │      FRONTEND         │  │
│   │  Port 9000   │────►│    Port 8000      │────►│     Port 3000         │  │
│   │              │     │   (FastAPI)       │     │  (React + Vite)       │  │
│   │ machine_     │     │                  │◄────│                       │  │
│   │ engine.py    │     │   main.py         │ WS  │   App.tsx             │  │
│   │ server.py    │     │   agent.py        │     │   Live Charts         │  │
│   │ ui.html      │     │   pure_lstm.py    │     │   AI Chat             │  │
│   └──────────────┘     └────────┬─────────┘     └───────────────────────┘  │
│                                 │                                           │
│                    ┌────────────┼────────────┐                              │
│                    │            │            │                              │
│              ┌─────▼──┐  ┌─────▼──┐  ┌─────▼──┐                          │
│              │SQLite  │  │ LSTM   │  │LangGraph│                          │
│              │WorkOrdr│  │RUL     │  │Agent    │                          │
│              │SensorLg│  │Model   │  │Workflow │                          │
│              └────────┘  └────────┘  └─────┬───┘                          │
│                                            │                               │
└────────────────────────────────────────────┼───────────────────────────────┘
                                             │
                    ┌────────────────────────▼──────────────────────────┐
                    │                  AWS CLOUD                         │
                    │                                                    │
                    │  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
                    │  │ Bedrock  │  │DynamoDB  │  │     SNS      │   │
                    │  │ Claude   │  │3 Tables  │  │ SMS + Email  │   │
                    │  │Haiku 4.5 │  │          │  │  Alerts      │   │
                    │  └──────────┘  └──────────┘  └──────────────┘   │
                    │                                                    │
                    │  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
                    │  │   S3     │  │ Lambda   │  │   Gmail      │   │
                    │  │PDF+JSON  │  │ Agent    │  │    SMTP      │   │
                    │  │ Reports  │  │ 24/7     │  │   Email      │   │
                    │  └──────────┘  └──────────┘  └──────────────┘   │
                    └────────────────────────────────────────────────────┘
```

---

## 2. Data Flow Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                    NORMAL OPERATION LOOP                        │
│                      (every 1 second)                           │
└─────────────────────────────────────────────────────────────────┘

  ┌─────────────┐
  │  Simulator  │
  │  Port 9000  │
  │             │
  │ volt=170    │
  │ rotate=450  │
  │ pressure=100│
  │ vibration=40│
  └──────┬──────┘
         │ GET /api/state
         ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                    main.py broadcast loop                   │
  │                                                             │
  │  1. Fetch reading from Simulator                            │
  │     └─ if down → use internal SensorSimulator fallback      │
  │                                                             │
  │  2. Append to history buffer (last 24 readings)             │
  │                                                             │
  │  3. LSTM Model prediction                                   │
  │     └─ 12 features → RUL score → years/days/hours          │
  │     └─ health_pct = ml_health × physics_health × 100       │
  │                                                             │
  │  4. DynamoDB upsert (mw_machine_state)                      │
  │  5. DynamoDB append (mw_sensor_timeseries)                  │
  │  6. WebSocket broadcast → Frontend updates                  │
  │                                                             │
  │  7. is_anomaly? ──No──► loop back                           │
  │                  │                                          │
  │                 Yes                                         │
  │                  ▼                                          │
  │           handle_anomaly()                                  │
  └─────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────┐
│                    ANOMALY WORKFLOW                             │
└─────────────────────────────────────────────────────────────────┘

  is_anomaly = True
         │
         ▼
  ┌─────────────────┐
  │  LangGraph      │
  │  Agent START    │
  └────────┬────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  NODE 1: analyze_sensor_data                                │
  │                                                             │
  │  Sends to Bedrock Claude Haiku 4.5:                         │
  │  → volt, rotate, pressure, vibration, RUL                   │
  │                                                             │
  │  Returns:                                                   │
  │  → fault_type  (Overvoltage / Bearing Failure / etc.)       │
  │  → severity    (P1 / P2 / P3)                               │
  │  → can_auto_fix (True / False)                              │
  └────────┬────────────────────────────────────────────────────┘
           │
           ▼
  ┌────────────────┐
  │    ROUTER      │
  │  can_auto_fix? │
  └───┬────────┬───┘
      │        │
     Yes       No
      │        │
      ▼        ▼
┌──────────┐  ┌──────────────────────┐
│ NODE 2a  │  │ NODE 2b              │
│ auto_fix │  │ manual_workflow      │
│          │  │                      │
│ Claude   │  │ Claude generates     │
│ calculates  │ step-by-step         │
│ safe     │  │ technician procedure │
│ params   │  │                      │
│          │  │ Sets machine to      │
│ POST to  │  │ safe idle state      │
│ Simulator│  └──────────┬───────────┘
│ /api/    │             │
│ params   │             │
└────┬─────┘             │
     └─────────┬─────────┘
               │
               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                  POST-AGENT ACTIONS                         │
  │                                                             │
  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐  │
  │  │   SQLite    │   │  DynamoDB   │   │       S3        │  │
  │  │             │   │             │   │                 │  │
  │  │ WorkOrder   │   │ mw_alerts   │   │ JSON report     │  │
  │  │ table       │   │ table       │   │ PDF report      │  │
  │  │             │   │             │   │ (reportlab)     │  │
  │  └─────────────┘   └─────────────┘   └─────────────────┘  │
  │                                                             │
  │  ┌─────────────┐   ┌─────────────────────────────────────┐ │
  │  │   Gmail     │   │              SNS                    │ │
  │  │   SMTP      │   │                                     │ │
  │  │             │   │  machinewhisperer-alerts topic      │ │
  │  │ HTML email  │   │  → Email to 4 subscribers           │ │
  │  │ to          │   │  → SMS to subscribed phones         │ │
  │  │ recipient   │   │                                     │ │
  │  └─────────────┘   └─────────────────────────────────────┘ │
  └─────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────┐
│                    FRONTEND INTERACTION                         │
└─────────────────────────────────────────────────────────────────┘

  User opens http://54.89.167.234:3000
         │
         ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  React App (App.tsx)                                        │
  │                                                             │
  │  WebSocket ws://backend:8000/ws/sensors                     │
  │  └─ receives reading every 1 second                         │
  │  └─ updates 4 live charts                                   │
  │  └─ updates RUL display + health bar                        │
  │  └─ detects anomaly → fetches work orders                   │
  │                                                             │
  │  ┌──────────────────┐    ┌──────────────────────────────┐  │
  │  │  "Simulate Fault"│    │  AI Assistant Chat           │  │
  │  │  button          │    │                              │  │
  │  │                  │    │  User types question         │  │
  │  │  POST            │    │  POST /api/chat              │  │
  │  │  /api/trigger-   │    │  → Bedrock Claude answers    │  │
  │  │  anomaly         │    │  with live sensor context    │  │
  │  └──────────────────┘    └──────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────┐
│                    AWS LAMBDA (24/7 Cloud Agent)                │
└─────────────────────────────────────────────────────────────────┘

  External system / API call
         │
         ▼ POST https://<lambda-url>/
  ┌─────────────────────────────────────────────────────────────┐
  │  lambda_handler.py                                          │
  │                                                             │
  │  action = health_check      → check all services           │
  │  action = analyze_anomaly   → full agent + DynamoDB + SNS  │
  │  action = chat_query        → Bedrock AI answer            │
  │  action = get_machine_state → DynamoDB read                │
  │  action = get_alerts        → DynamoDB read                │
  │  action = get_stats         → DynamoDB time-series stats   │
  │  action = get_recent_readings → DynamoDB query             │
  │                                                             │
  │  Returns: {statusCode, headers, body}                       │
  └─────────────────────────────────────────────────────────────┘
```

---

## 3. Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TECHNOLOGY STACK                             │
├──────────────────┬──────────────────────────────────────────────┤
│  LAYER           │  TECHNOLOGY                                  │
├──────────────────┼──────────────────────────────────────────────┤
│  Frontend        │  React 18 + TypeScript + Vite                │
│                  │  Tailwind CSS                                 │
│                  │  Recharts (live charts)                       │
│                  │  react-markdown (AI chat)                     │
│                  │  WebSocket (native browser API)               │
├──────────────────┼──────────────────────────────────────────────┤
│  Backend API     │  FastAPI + Uvicorn                           │
│                  │  Python 3.12                                  │
│                  │  WebSocket (real-time streaming)              │
│                  │  SQLAlchemy + SQLite                          │
├──────────────────┼──────────────────────────────────────────────┤
│  ML / AI         │  Pure NumPy LSTM (RUL prediction)            │
│                  │  LangGraph (agent state machine)              │
│                  │  LangChain Core                               │
│                  │  AWS Bedrock Claude Haiku 4.5                 │
├──────────────────┼──────────────────────────────────────────────┤
│  AWS Services    │  DynamoDB (3 tables)                         │
│                  │  SNS (pub/sub alerts)                         │
│                  │  S3 (report storage)                          │
│                  │  Lambda (serverless agent)                    │
│                  │  Bedrock (LLM inference)                      │
│                  │  EC2 t2.small (hosting)                       │
├──────────────────┼──────────────────────────────────────────────┤
│  Notifications   │  Amazon SNS → Email + SMS                    │
│                  │  Gmail SMTP → Direct email                    │
├──────────────────┼──────────────────────────────────────────────┤
│  DevOps          │  GitHub (source control)                      │
│                  │  systemd (process management)                 │
│                  │  Ubuntu 24.04 LTS                             │
└──────────────────┴──────────────────────────────────────────────┘
```

---

## 4. DynamoDB Table Design

```
┌─────────────────────────────────────────────────────────────────┐
│  mw_machine_state                                               │
│  PK: machine_id (S)                                             │
├─────────────────────────────────────────────────────────────────┤
│  machine_id │ volt │ rotate │ pressure │ vibration │ rul        │
│  health_pct │ is_anomaly │ temperature │ updated_at             │
│                                                                 │
│  → 1 row per machine, overwritten every second                  │
│  → "latest state" snapshot                                      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  mw_alerts                                                      │
│  PK: machine_id (S)   SK: alert_id (S) UUID                     │
├─────────────────────────────────────────────────────────────────┤
│  machine_id │ alert_id │ fault_type │ severity                  │
│  recommended_action │ explanation │ volt │ rotate               │
│  pressure │ vibration │ auto_fixed │ rul │ timestamp            │
│                                                                 │
│  → 1 row per anomaly event, never deleted                       │
│  → full alert history                                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  mw_sensor_timeseries                                           │
│  PK: machine_id (S)   SK: timestamp_ms (S)                      │
├─────────────────────────────────────────────────────────────────┤
│  machine_id │ timestamp_ms │ timestamp_iso                      │
│  volt │ rotate │ pressure │ vibration │ is_anomaly              │
│  rul │ health_pct │ temperature │ ttl (7 days)                  │
│                                                                 │
│  → 1 row per second per machine                                 │
│  → auto-deleted after 7 days via TTL                            │
│  → used for charts, stats, anomaly history                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. LangGraph Agent State Machine

```
         ┌─────────┐
         │  START  │
         └────┬────┘
              │
              ▼
    ┌──────────────────┐
    │     ANALYZE      │  ← Bedrock Claude Haiku 4.5
    │                  │
    │  Input:          │
    │  volt, rotate,   │
    │  pressure,       │
    │  vibration, rul  │
    │                  │
    │  Output:         │
    │  fault_type      │
    │  severity        │
    │  can_auto_fix    │
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │     ROUTER       │
    │  can_auto_fix?   │
    └──┬───────────┬───┘
       │           │
      YES          NO
       │           │
       ▼           ▼
┌──────────┐  ┌────────────────┐
│ AUTO_FIX │  │MANUAL_WORKFLOW │
│          │  │                │
│ Claude   │  │ Claude writes  │
│ computes │  │ step-by-step   │
│ safe     │  │ procedure for  │
│ params   │  │ technician     │
│          │  │                │
│ Pushes   │  │ Sets machine   │
│ to sim   │  │ to safe idle   │
└────┬─────┘  └───────┬────────┘
     │                │
     └────────┬───────┘
              │
              ▼
           ┌─────┐
           │ END │
           └─────┘
```

---

## 6. Deployment Architecture (EC2)

```
                        INTERNET
                            │
                            ▼
                   ┌─────────────────┐
                   │   AWS EC2       │
                   │   t2.small      │
                   │   Ubuntu 24.04  │
                   │   54.89.167.234 │
                   └────────┬────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        Port 3000      Port 8000      Port 9000
     ┌──────────┐   ┌──────────┐   ┌──────────┐
     │Frontend  │   │ Backend  │   │Simulator │
     │          │   │          │   │          │
     │ serve    │   │ FastAPI  │   │ FastAPI  │
     │ -s dist  │   │ Uvicorn  │   │ Uvicorn  │
     │          │   │          │   │          │
     │ systemd  │   │ systemd  │   │ systemd  │
     │ service  │   │ service  │   │ service  │
     └──────────┘   └──────────┘   └──────────┘
                         │
                         │ boto3
                         ▼
              ┌──────────────────────┐
              │     AWS Services     │
              │  Bedrock / DynamoDB  │
              │  SNS / S3 / Lambda   │
              └──────────────────────┘
```

# Secure Deadlock Detection and Database Access Control System

Implementation of the LogicShield project proposal (OSDBMS-V-2026-T095) for
TCS 502 (Operating Systems) & TCS 503 (Database Management Systems).

## Phase-II Project Progress


**Phase-II: Core Logic Development and Initial Integration**

The Phase-II implementation focuses on developing and integrating the
core backend logic of the proposed Secure Deadlock Detection and Database
Access Control System.

The current Phase-II codebase focuses on database management,
authentication and access control, transaction/resource management,
deadlock detection, and the initial integration of these modules through Flask.

---

## What's Implemented in Phase-II

| Core Module | File | Team Member | Status |
|---|---|---|---|
| Authentication & Authorization | `access_control.py` | Ayushman Guleriya | Implemented |
| Role-Based Access Control (RBAC) | `access_control.py` | Ayushman Guleriya | Implemented |
| Database Interface Layer | `db.py` | Ridhima Sharma | Implemented |
| Database Schema & Operations | `db.py` | Ridhima Sharma | Implemented |
| Transaction & Resource Management | `transaction_manager.py` | Ridhima Sharma | Implemented |
| Lock Management | `transaction_manager.py` | Ridhima Sharma | Implemented |
| Deadlock Detection Logic | `deadlock.py` | Shivarth Puri | Implemented |
| Application Integration | `app.py` | Pavni Jain | Implemented |

The Phase-II repository contains the core logic files required for
developing the backend foundation of the proposed system.

---

## Module Description

### 1. Authentication and Access Control

**File:** `access_control.py`  
**Team Member:** Ayushman Guleriya

The module provides authentication and role-based access control.

The system defines three roles:

- `admin`
- `manager`
- `user`

Different roles have different permissions for accessing database
resources. Access requests can be checked before a resource is used.

---

### 2. Database Interface

**File:** `db.py`  
**Team Member:** Ridhima Sharma

The database module provides the database connection and database
operations required by the application.

The current Phase-II implementation uses SQLite through Python's
built-in `sqlite3` module.

The database is created automatically when the application is started.

The database layer is designed so that other modules interact with the
database through `db.py`.

---

### 3. Transaction and Resource Management

**File:** `transaction_manager.py`  
**Team Member:** Ridhima Sharma

This module manages transactions and resource locking.

The implementation supports:

- Starting transactions
- Requesting resources
- Shared/read locks
- Exclusive/write locks
- Lock conflicts
- Waiting transactions
- Commit operations
- Rollback operations
- Releasing resources

The transaction manager provides the resource and lock-management
foundation required for deadlock detection.

---

### 4. Deadlock Detection

**File:** `deadlock.py`  
**Team Member:** Shivarth Puri

This module contains the core logic for detecting deadlocks in the
transaction/resource management system.

The deadlock detection component works with transaction dependencies
created by resource and lock conflicts.

The module provides the foundation for:

- Identifying waiting transactions
- Representing transaction dependencies
- Detecting cyclic dependencies
- Identifying potential deadlock situations

Further deadlock recovery and optimization can be extended in the
subsequent development phases.

---

### 5. Flask Application Integration

**File:** `app.py`  
**Team Member:** Pavni Jain

The Flask application acts as the main application layer and connects
the core modules.

It provides the application structure required to interact with:

- Authentication and access control
- Database operations
- Transaction management
- Resource management
- Deadlock detection

---

## Phase-II Project Flow

The current Phase-II core logic follows this general flow:

User Request
    ↓
Authentication
    ↓
Access Control
    ↓
Resource Request
    ↓
Transaction Manager
    ↓
Lock Management
    ↓
Deadlock Detection
    ↓
Database Operation

This provides the backend foundation for the complete system.

---

## Phase-II Repository Structure

```text
deadlock_project/
│
├── app.py
├── db.py
├── access_control.py
├── transaction_manager.py
├── deadlock.py
└── requirements.txt

## 👥 Team Members
-pavni jain(Team Leader)
-ridhima sharma
-shivarth puri
-ayushman guleriya

## 👨‍🏫 Mentor
Dr.Mohammad Wazid

## 📚 References
- Operating System Concepts – Silberschatz, Galvin & Gagne
- Relevant IEEE research papers

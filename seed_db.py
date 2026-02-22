"""
Seed script for manufacturing demo database.
Run once to create and populate the SQLite database.
"""

import sqlite3
import random
from datetime import datetime, timedelta

DB_PATH = "manufacturing.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS factories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    country TEXT NOT NULL,
    established_year INTEGER,
    total_area_sqm REAL,
    active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS production_lines (
    id INTEGER PRIMARY KEY,
    factory_id INTEGER NOT NULL REFERENCES factories(id),
    name TEXT NOT NULL,
    product_type TEXT NOT NULL,
    capacity_units_per_day INTEGER,
    active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY,
    production_line_id INTEGER NOT NULL REFERENCES production_lines(id),
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    manufacturer TEXT NOT NULL,
    installed_date TEXT,
    last_maintenance_date TEXT,
    status TEXT CHECK(status IN ('operational','maintenance','offline')) DEFAULT 'operational',
    age_years REAL,
    cumulative_downtime_hours REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    factory_id INTEGER NOT NULL REFERENCES factories(id),
    shift TEXT CHECK(shift IN ('morning','afternoon','night')),
    hire_date TEXT,
    active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    contact_email TEXT,
    lead_time_days INTEGER,
    reliability_score REAL CHECK(reliability_score BETWEEN 0 AND 10)
);

CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sku TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    unit_cost REAL,
    stock_quantity INTEGER DEFAULT 0,
    reorder_threshold INTEGER DEFAULT 50,
    supplier_id INTEGER REFERENCES suppliers(id)
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    part_id INTEGER NOT NULL REFERENCES parts(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    order_date TEXT NOT NULL,
    expected_delivery TEXT,
    actual_delivery TEXT,
    status TEXT CHECK(status IN ('pending','shipped','delivered','cancelled')) DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS work_orders (
    id INTEGER PRIMARY KEY,
    production_line_id INTEGER NOT NULL REFERENCES production_lines(id),
    operator_id INTEGER NOT NULL REFERENCES employees(id),
    product_name TEXT NOT NULL,
    quantity_target INTEGER NOT NULL,
    quantity_produced INTEGER DEFAULT 0,
    start_date TEXT,
    end_date TEXT,
    status TEXT CHECK(status IN ('planned','in_progress','completed','cancelled')) DEFAULT 'planned',
    priority TEXT CHECK(priority IN ('low','medium','high','critical')) DEFAULT 'medium'
);

CREATE TABLE IF NOT EXISTS work_order_parts (
    id INTEGER PRIMARY KEY,
    work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
    part_id INTEGER NOT NULL REFERENCES parts(id),
    quantity_required INTEGER NOT NULL,
    quantity_used INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quality_inspections (
    id INTEGER PRIMARY KEY,
    work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
    inspector_id INTEGER NOT NULL REFERENCES employees(id),
    inspection_date TEXT NOT NULL,
    result TEXT CHECK(result IN ('pass','fail','conditional_pass')) NOT NULL,
    defect_type TEXT,
    defect_count INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS maintenance_logs (
    id INTEGER PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES machines(id),
    technician_id INTEGER NOT NULL REFERENCES employees(id),
    maintenance_date TEXT NOT NULL,
    maintenance_type TEXT CHECK(maintenance_type IN ('preventive','corrective','emergency')) NOT NULL,
    downtime_hours REAL NOT NULL,
    cost REAL,
    description TEXT,
    resolved BOOLEAN DEFAULT 1
);
"""

def random_date(start_days_ago=365, end_days_ago=0):
    delta = random.randint(end_days_ago, start_days_ago)
    return (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")

def seed(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    c = conn.cursor()

    # --- Factories ---
    factories = [
        (1, "NordSteel Leipzig",     "Leipzig",     "Germany", 1987, 45000),
        (2, "PolyFab Milano",         "Milan",        "Italy",   1995, 32000),
        (3, "AeroTech Toulouse",      "Toulouse",     "France",  2001, 28000),
        (4, "PrecisionWorks Gdańsk",  "Gdańsk",       "Poland",  2008, 19000),
        (5, "MetalCore Monterrey",    "Monterrey",    "Mexico",  2012, 22000),
    ]
    c.executemany("INSERT OR IGNORE INTO factories VALUES (?,?,?,?,?,?,1)", factories)

    # --- Production Lines ---
    lines = [
        (1,  1, "Steel Casting Line A",       "Structural Steel",    800),
        (2,  1, "Steel Casting Line B",       "Flat Rolled Steel",   600),
        (3,  1, "Quality Control Line",       "Inspection",          1200),
        (4,  2, "Polymer Extrusion Line 1",   "PVC Profiles",        500),
        (5,  2, "Polymer Extrusion Line 2",   "HDPE Pipes",          400),
        (6,  3, "Fuselage Assembly A",        "Aircraft Fuselage",   10),
        (7,  3, "Wing Component Line",        "Wing Structures",     8),
        (8,  4, "CNC Machining Center",       "Precision Parts",     200),
        (9,  4, "Surface Treatment Line",     "Coated Parts",        300),
        (10, 5, "Stamping Press Line",        "Metal Stampings",     1000),
    ]
    c.executemany("INSERT OR IGNORE INTO production_lines VALUES (?,?,?,?,?,1)", lines)

    # --- Machines ---
    machine_data = [
        # (id, line_id, name, model, manufacturer, installed, last_maint, status, age, downtime)
        (1,  1, "Arc Furnace #1",        "EAF-500",    "Siemens",       "2010-03-15", "2024-10-01", "operational", 14.0, 120),
        (2,  1, "Continuous Caster A",   "CC-3000",    "Danieli",       "2012-06-20", "2024-11-15", "operational", 12.0, 80),
        (3,  2, "Rolling Mill X1",       "RM-800",     "SMS Group",     "2015-01-10", "2024-09-20", "operational", 9.5,  65),
        (4,  2, "Coiling Machine B2",    "CM-200",     "Primetals",     "2018-04-05", "2024-12-01", "operational", 6.5,  30),
        (5,  3, "Ultrasonic Tester",     "UT-Pro X",   "Olympus",       "2020-07-11", "2025-01-10", "operational", 4.0,  10),
        (6,  4, "Extruder PE-90",        "PE-90L",     "Krauss-Maffei", "2014-09-30", "2024-08-01", "maintenance", 10.0, 200),
        (7,  4, "Haul-Off Unit H4",      "HO-400",     "Battenfeld",    "2017-02-14", "2024-10-15", "operational", 7.5,  55),
        (8,  5, "Extruder PE-120",       "PE-120H",    "Krauss-Maffei", "2019-11-25", "2025-01-05", "operational", 5.0,  25),
        (9,  6, "Riveting Robot RR-1",   "RR-700",     "KUKA",          "2016-05-20", "2024-12-20", "operational", 8.5,  90),
        (10, 6, "Panel Joining Unit",    "PJ-200",     "Broetje",       "2018-08-01", "2025-01-20", "operational", 6.5,  45),
        (11, 7, "Spar Drilling Machine", "SDM-5X",     "Dornier",       "2013-03-10", "2024-07-15", "offline",     11.5, 350),
        (12, 8, "CNC Lathe L1",         "Mazak-QT25", "Mazak",         "2021-01-15", "2025-01-25", "operational", 4.0,  15),
        (13, 8, "5-Axis Mill M3",       "DMU-95",     "DMG Mori",      "2022-06-10", "2025-02-01", "operational", 2.5,  5),
        (14, 9, "Shot Blast Unit SB2",   "SB-600",     "Wheelabrator",  "2016-10-20", "2024-09-10", "operational", 8.0,  70),
        (15, 10,"Hydraulic Press P1",    "HP-1600T",   "Schuler",       "2017-07-05", "2024-11-20", "operational", 7.5,  95),
        (16, 10,"Stamping Die System",   "SDS-800",    "Trumpf",        "2020-03-15", "2025-01-15", "operational", 4.5,  20),
    ]
    c.executemany("INSERT OR IGNORE INTO machines VALUES (?,?,?,?,?,?,?,?,?,?)", machine_data)

    # --- Employees ---
    roles = ["Operator", "Senior Operator", "Inspector", "Technician", "Shift Supervisor", "Quality Engineer"]
    shifts = ["morning", "afternoon", "night"]
    names = [
        "Lukas Becker","Maria Rossi","Jean Dupont","Anna Kowalski","Carlos Mendez",
        "Sophie Laurent","Piotr Nowak","Elena Müller","Ricardo García","Hana Novak",
        "Thomas Braun","Isabela Silva","Marek Wójcik","Claire Bernard","Diego Torres",
        "Monika Krol","Stefan Huber","Fatima Benali","Andrei Popescu","Laura Esposito",
        "Hans Zimmermann","Katarzyna Dąbrowska","Miguel Fernández","Sara Bianchi","Robert Klein",
    ]
    employees = []
    for i, name in enumerate(names, 1):
        fid = random.randint(1, 5)
        employees.append((i, name, random.choice(roles), fid, random.choice(shifts), random_date(3000, 365), 1))
    c.executemany("INSERT OR IGNORE INTO employees VALUES (?,?,?,?,?,?,?)", employees)

    # --- Suppliers ---
    suppliers = [
        (1, "ThyssenKrupp Materials",  "Germany",  "orders@tk-materials.de",  14, 9.1),
        (2, "SABIC Europe",            "Netherlands","supply@sabic.eu",         21, 8.4),
        (3, "Hexcel Composites",       "USA",        "orders@hexcel.com",       28, 8.9),
        (4, "Fastener World",          "China",      "sales@fastenerworld.cn",  35, 6.2),
        (5, "Lubrizol Additives",      "USA",        "orders@lubrizol.com",     10, 9.5),
        (6, "Sandvik Tooling",         "Sweden",     "tools@sandvik.com",        7, 9.7),
        (7, "IGS Gaskets",             "Italy",      "info@igsgaskets.it",      18, 7.8),
        (8, "Nippon Steel Supply",     "Japan",      "export@nippon-ss.jp",     25, 8.6),
    ]
    c.executemany("INSERT OR IGNORE INTO suppliers VALUES (?,?,?,?,?,?)", suppliers)

    # --- Parts ---
    parts_data = [
        (1,  "High-Carbon Steel Billet",  "SKU-1001", "Raw Material",   480.00, 320, 100, 1),
        (2,  "PVC Resin Grade K67",       "SKU-1002", "Raw Material",   120.00, 180, 80,  2),
        (3,  "Carbon Fiber Prepreg",      "SKU-1003", "Composite",      950.00, 45,  20,  3),
        (4,  "M12 Hex Bolt (box/100)",    "SKU-2001", "Fastener",        18.50, 850, 200, 4),
        (5,  "M8 Lock Nut (box/100)",     "SKU-2002", "Fastener",         9.20, 620, 200, 4),
        (6,  "Industrial Lubricant 5L",   "SKU-3001", "Consumable",      45.00, 95,  40,  5),
        (7,  "Tungsten Carbide Insert",   "SKU-3002", "Tooling",        230.00, 60,  25,  6),
        (8,  "Hydraulic Seal Kit",        "SKU-3003", "Maintenance",     88.00, 35,  30,  7),
        (9,  "HDPE Granules 25kg",        "SKU-1004", "Raw Material",    85.00, 260, 80,  2),
        (10, "Aluminum Sheet 2mm",        "SKU-1005", "Raw Material",   310.00, 140, 50,  8),
        (11, "Titanium Fastener Kit",     "SKU-2003", "Fastener",       175.00, 28,  20,  4),
        (12, "Welding Wire ER70S-6",      "SKU-3004", "Consumable",     62.00,  110, 50,  1),
    ]
    c.executemany("INSERT OR IGNORE INTO parts VALUES (?,?,?,?,?,?,?,?)", parts_data)

    # --- Purchase Orders ---
    po_statuses = ["pending","shipped","delivered","delivered","delivered","cancelled"]
    purchase_orders = []
    for i in range(1, 61):
        sup_id = random.randint(1, 8)
        part_id = random.randint(1, 12)
        qty = random.randint(50, 500)
        price = round(random.uniform(10, 600), 2)
        order_date = random_date(180, 10)
        exp_delivery = (datetime.strptime(order_date, "%Y-%m-%d") + timedelta(days=random.randint(7,40))).strftime("%Y-%m-%d")
        status = random.choice(po_statuses)
        actual_delivery = None
        if status == "delivered":
            actual_delivery = (datetime.strptime(exp_delivery, "%Y-%m-%d") + timedelta(days=random.randint(-3, 15))).strftime("%Y-%m-%d")
        purchase_orders.append((i, sup_id, part_id, qty, price, order_date, exp_delivery, actual_delivery, status))
    c.executemany("INSERT OR IGNORE INTO purchase_orders VALUES (?,?,?,?,?,?,?,?,?)", purchase_orders)

    # --- Work Orders ---
    products = [
        "HEA 200 Beam", "IPE 300 Beam", "Hot-Rolled Coil", "PVC Window Profile",
        "HDPE Water Pipe 110mm", "Fuselage Panel Section 12", "Wing Rib Assembly",
        "Precision Shaft 40mm", "Brake Disc Housing", "Metal Stamping Bracket A",
        "Stamping Bracket B", "Aircraft Skin Panel",
    ]
    line_product_map = {1:"HEA 200 Beam",2:"Hot-Rolled Coil",3:"HEA 200 Beam",4:"PVC Window Profile",
                        5:"HDPE Water Pipe 110mm",6:"Fuselage Panel Section 12",7:"Wing Rib Assembly",
                        8:"Precision Shaft 40mm",9:"Brake Disc Housing",10:"Metal Stamping Bracket A"}
    statuses_wo = ["planned","in_progress","completed","completed","completed","cancelled"]
    priorities = ["low","medium","high","critical"]
    work_orders = []
    for i in range(1, 201):
        line_id = random.randint(1, 10)
        op_id = random.randint(1, 25)
        product = line_product_map.get(line_id, random.choice(products))
        target = random.randint(50, 500)
        status = random.choice(statuses_wo)
        produced = target if status == "completed" else (random.randint(0, target) if status == "in_progress" else 0)
        start = random_date(200, 5)
        end = None
        if status == "completed":
            end = (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=random.randint(1, 14))).strftime("%Y-%m-%d")
        priority = random.choice(priorities)
        work_orders.append((i, line_id, op_id, product, target, produced, start, end, status, priority))
    c.executemany("INSERT OR IGNORE INTO work_orders VALUES (?,?,?,?,?,?,?,?,?,?)", work_orders)

    # --- Work Order Parts ---
    wop = []
    wop_id = 1
    for wo_id in range(1, 201):
        for _ in range(random.randint(1, 3)):
            part_id = random.randint(1, 12)
            qty_req = random.randint(5, 100)
            qty_used = qty_req if random.random() > 0.2 else random.randint(0, qty_req)
            wop.append((wop_id, wo_id, part_id, qty_req, qty_used))
            wop_id += 1
    c.executemany("INSERT OR IGNORE INTO work_order_parts VALUES (?,?,?,?,?)", wop)

    # --- Quality Inspections ---
    defect_types = ["Dimensional deviation","Surface crack","Porosity","Delamination",
                    "Weld defect","Hardness out of spec","Paint adhesion failure", None, None, None]
    inspections = []
    for i in range(1, 501):
        wo_id = random.randint(1, 200)
        inspector_id = random.randint(1, 25)
        date = random_date(200, 1)
        result = random.choices(["pass","fail","conditional_pass"], weights=[70, 15, 15])[0]
        defect = random.choice(defect_types) if result != "pass" else None
        defect_count = random.randint(1, 8) if defect else 0
        inspections.append((i, wo_id, inspector_id, date, result, defect, defect_count, None))
    c.executemany("INSERT OR IGNORE INTO quality_inspections VALUES (?,?,?,?,?,?,?,?)", inspections)

    # --- Maintenance Logs ---
    maint_types = ["preventive","corrective","emergency"]
    descriptions = [
        "Routine lubrication and belt replacement",
        "Bearing replacement after vibration alert",
        "Emergency shutdown due to overheating, coolant replaced",
        "Calibration and sensor alignment",
        "Hydraulic seal replacement",
        "Conveyor chain replacement",
        "Electrical fault diagnosis and repair",
        "Scheduled annual inspection",
        "Motor winding repair",
        "Control panel firmware update and diagnostics",
    ]
    maint_logs = []
    for i in range(1, 151):
        machine_id = random.randint(1, 16)
        tech_id = random.randint(1, 25)
        date = random_date(365, 1)
        mtype = random.choices(maint_types, weights=[50, 35, 15])[0]
        downtime = round(random.uniform(0.5, 48.0), 1) if mtype == "emergency" else round(random.uniform(0.5, 12.0), 1)
        cost = round(random.uniform(200, 15000), 2)
        desc = random.choice(descriptions)
        resolved = 1 if mtype != "emergency" or random.random() > 0.1 else 0
        maint_logs.append((i, machine_id, tech_id, date, mtype, downtime, cost, desc, resolved))
    c.executemany("INSERT OR IGNORE INTO maintenance_logs VALUES (?,?,?,?,?,?,?,?,?)", maint_logs)

    conn.commit()
    conn.close()
    print(f"✅ Database seeded successfully at {db_path}")
    print("Tables: factories, production_lines, machines, employees, suppliers,")
    print("        parts, purchase_orders, work_orders, work_order_parts,")
    print("        quality_inspections, maintenance_logs")

if __name__ == "__main__":
    seed()
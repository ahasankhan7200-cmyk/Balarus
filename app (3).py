import streamlit as st
import sqlite3, os, datetime as dt
from contextlib import contextmanager

st.set_page_config(page_title="Balarus Spare House ERP", page_icon="🚜", layout="wide")
SHOP = "Balarus Spare House"
DB_PATH = os.environ.get("DB_PATH", "balarus.db")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "admin123")

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, part_no TEXT, tractor_model TEXT, category TEXT,
 buy_price REAL DEFAULT 0, retail_price REAL DEFAULT 0, wholesale_price REAL DEFAULT 0,
 stock REAL DEFAULT 0, min_stock REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS parties(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT,
 type TEXT NOT NULL CHECK(type IN ('customer','supplier')));
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, name TEXT UNIQUE, opening REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS txns(
 id INTEGER PRIMARY KEY, date TEXT, account_id INTEGER, kind TEXT, amount REAL,
 party_id INTEGER, ref TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS sales(
 id INTEGER PRIMARY KEY, date TEXT, party_id INTEGER, kind TEXT, total REAL, paid REAL, account_id INTEGER);
CREATE TABLE IF NOT EXISTS sale_items(
 id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER, qty REAL, price REAL, cost REAL);
CREATE TABLE IF NOT EXISTS purchases(
 id INTEGER PRIMARY KEY, date TEXT, party_id INTEGER, total REAL, paid REAL, account_id INTEGER);
CREATE TABLE IF NOT EXISTS purchase_items(
 id INTEGER PRIMARY KEY, purchase_id INTEGER, product_id INTEGER, qty REAL, cost REAL);
"""

def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
            c.executemany("INSERT INTO accounts(name) VALUES(?)", [("Cash",),("Bank",),("bKash",)])
init_db()

def fetch(sql, params=()):
    with conn() as c: return c.execute(sql, params).fetchall()
def fetchone(sql, params=()):
    with conn() as c: return c.execute(sql, params).fetchone()
def execute(sql, params=()):
    with conn() as c:
        cur=c.execute(sql, params); c.commit(); return cur.lastrowid
def today(): return dt.date.today().isoformat()
def money(x): return f"৳{float(x or 0):,.2f}"

def accounts():
    return fetch("SELECT * FROM accounts ORDER BY id")
def account_balances():
    return fetch("""SELECT a.id,a.name,a.opening+COALESCE(SUM(t.amount),0) balance
                    FROM accounts a LEFT JOIN txns t ON t.account_id=a.id GROUP BY a.id ORDER BY a.id""")
def party_due(p):
    if p["type"]=="customer":
        sales=fetchone("SELECT COALESCE(SUM(total-paid),0) x FROM sales WHERE party_id=?",(p["id"],))["x"]
        received=fetchone("SELECT COALESCE(SUM(amount),0) x FROM txns WHERE party_id=? AND kind='due_in'",(p["id"],))["x"]
        return sales-received
    purchases=fetchone("SELECT COALESCE(SUM(total-paid),0) x FROM purchases WHERE party_id=?",(p["id"],))["x"]
    payments=fetchone("SELECT COALESCE(SUM(amount),0) x FROM txns WHERE party_id=? AND kind='due_out'",(p["id"],))["x"]
    return purchases+payments
def parties(kind=None):
    if kind: return fetch("SELECT * FROM parties WHERE type=? ORDER BY name",(kind,))
    return fetch("SELECT * FROM parties ORDER BY name")
def product_list():
    return fetch("SELECT * FROM products ORDER BY name")
def fmt_table(rows):
    return [dict(r) for r in rows]

# Login
if "authenticated" not in st.session_state: st.session_state.authenticated=False
if not st.session_state.authenticated:
    st.title("🚜 Balarus Spare House")
    st.subheader("ERP Login")
    with st.form("login"):
        password=st.text_input("Password", type="password")
        submitted=st.form_submit_button("Login", type="primary")
    if submitted:
        if password==APP_PASSWORD:
            st.session_state.authenticated=True; st.rerun()
        else: st.error("Incorrect password.")
    st.caption("Default password: admin123 — change APP_PASSWORD in deployment secrets/environment before use.")
    st.stop()

with st.sidebar:
    st.title("🚜 Balarus Spare House")
    page=st.radio("Navigation",["Dashboard","Products & Stock","Sales","Purchases","Customers & Suppliers","Money & Accounts","Reports"])
    st.divider()
    st.caption("Business management")
    if st.button("Log out"): st.session_state.authenticated=False; st.rerun()

st.title(page)

# Dashboard
if page=="Dashboard":
    sales_today=fetchone("SELECT COALESCE(SUM(total),0) n FROM sales WHERE date=?",(today(),))["n"]
    cash_total=sum(x["balance"] for x in account_balances())
    allp=parties()
    receivable=sum(party_due(p) for p in allp if p["type"]=="customer")
    payable=sum(party_due(p) for p in allp if p["type"]=="supplier")
    low=fetch("SELECT * FROM products WHERE stock<=min_stock ORDER BY stock")
    col1,col2,col3,col4=st.columns(4)
    col1.metric("Sales today",money(sales_today))
    col2.metric("Cash / accounts",money(cash_total))
    col3.metric("Customer receivable",money(receivable))
    col4.metric("Supplier payable",money(payable))
    st.subheader("Account balances")
    st.dataframe(fmt_table(account_balances()), use_container_width=True, hide_index=True)
    st.subheader("⚠️ Low-stock items")
    st.dataframe(fmt_table(low), use_container_width=True, hide_index=True)
    st.caption("Items at or below their minimum stock level.")

elif page=="Products & Stock":
    with st.expander("➕ Add a new spare part", expanded=True):
        with st.form("add_product"):
            c1,c2,c3=st.columns(3)
            name=c1.text_input("Product name *")
            partno=c2.text_input("Part number / SKU")
            model=c3.text_input("Tractor model")
            category=st.text_input("Category")
            c4,c5,c6,c7=st.columns(4)
            buy=c4.number_input("Purchase price",min_value=0.0)
            retail=c5.number_input("Retail price",min_value=0.0)
            wholesale=c6.number_input("Wholesale price",min_value=0.0)
            stock=c7.number_input("Opening stock",min_value=0.0)
            minimum=st.number_input("Minimum stock alert",min_value=0.0)
            if st.form_submit_button("Save product"):
                if name.strip():
                    execute("INSERT INTO products(name,part_no,tractor_model,category,buy_price,retail_price,wholesale_price,stock,min_stock) VALUES(?,?,?,?,?,?,?,?,?)",
                            (name,partno,model,category,buy,retail,wholesale,stock,minimum))
                    st.success("Product added."); st.rerun()
                else: st.error("Product name is required.")
    search=st.text_input("Search by name, part number or model")
    rows=fetch("SELECT * FROM products WHERE name LIKE ? OR part_no LIKE ? OR tractor_model LIKE ? ORDER BY name",
               (f"%{search}%",)*3)
    st.dataframe(fmt_table(rows),use_container_width=True,hide_index=True)
    st.download_button("Download product list CSV", data=__import__('pandas').DataFrame(fmt_table(rows)).to_csv(index=False), file_name="products.csv", mime="text/csv")

elif page=="Sales":
    prods=product_list(); cust=parties("customer"); accs=accounts()
    if not prods: st.warning("Add products first.")
    else:
        with st.form("sale_form"):
            sale_date=st.date_input("Date",dt.date.today())
            sale_type=st.selectbox("Sale type",["Retail","Wholesale"])
            customer=st.selectbox("Customer (optional for fully paid walk-in)",[None]+cust,format_func=lambda p:"Walk-in customer" if p is None else p["name"])
            account=st.selectbox("Receive payment into",accs,format_func=lambda a:a["name"])
            st.markdown("**Items (up to 5 rows)**")
            items=[]
            for i in range(5):
                c1,c2,c3=st.columns([3,1,1])
                product=c1.selectbox(f"Product {i+1}",[None]+prods,key=f"saleprod{i}",format_func=lambda p:"— Select —" if p is None else f'{p["name"]} | {p["part_no"] or ""} (stock {p["stock"]})')
                qty=c2.number_input(f"Qty {i+1}",min_value=0.0,key=f"saleqty{i}")
                defaultprice=0.0
                if product: defaultprice=product["retail_price"] if sale_type=="Retail" else product["wholesale_price"]
                price=c3.number_input(f"Unit price {i+1}",min_value=0.0,value=float(defaultprice),key=f"saleprice{i}")
                if product and qty>0: items.append((product,qty,price))
            paid=st.number_input("Amount received now (0 means none)",min_value=0.0)
            submitted=st.form_submit_button("Save sale",type="primary")
        if submitted:
            if not items: st.error("Choose at least one product and quantity.")
            elif any(qty>p["stock"] for p,qty,price in items): st.error("Insufficient stock for one or more selected products.")
            else:
                total=sum(qty*price for p,qty,price in items)
                pay=min(paid,total)
                if pay<total and customer is None: st.error("Select a customer for credit sales.")
                else:
                    sid=execute("INSERT INTO sales(date,party_id,kind,total,paid,account_id) VALUES(?,?,?,?,?,?)",
                        (sale_date.isoformat(),customer["id"] if customer else None,sale_type.lower(),total,pay,account["id"]))
                    for p,qty,price in items:
                        execute("INSERT INTO sale_items(sale_id,product_id,qty,price,cost) VALUES(?,?,?,?,?)",(sid,p["id"],qty,price,p["buy_price"]))
                        execute("UPDATE products SET stock=stock-? WHERE id=?",(qty,p["id"]))
                    if pay:
                        execute("INSERT INTO txns(date,account_id,kind,amount,party_id,ref) VALUES(?,?,?,?,?,?)",
                            (sale_date.isoformat(),account["id"],"sale",pay,customer["id"] if customer else None,f"Sale #{sid}"))
                    st.success(f"Sale #{sid} saved. Total {money(total)}; received {money(pay)}.")
                    st.rerun()
    st.subheader("Recent sales")
    st.dataframe(fmt_table(fetch("SELECT s.id,s.date,p.name customer,s.kind,s.total,s.paid,(s.total-s.paid) due FROM sales s LEFT JOIN parties p ON p.id=s.party_id ORDER BY s.id DESC LIMIT 25")),use_container_width=True,hide_index=True)

elif page=="Purchases":
    prods=product_list(); suppliers=parties("supplier"); accs=accounts()
    if not prods: st.warning("Add products first.")
    else:
        with st.form("purchase_form"):
            purchase_date=st.date_input("Purchase date",dt.date.today(),key="pdate")
            supplier=st.selectbox("Supplier",[None]+suppliers,format_func=lambda p:"Choose supplier" if p is None else p["name"])
            account=st.selectbox("Pay from account",accs,format_func=lambda a:a["name"],key="pacc")
            items=[]
            for i in range(5):
                c1,c2,c3=st.columns([3,1,1])
                product=c1.selectbox(f"Product {i+1}",[None]+prods,key=f"purchaseprod{i}",format_func=lambda p:"— Select —" if p is None else f'{p["name"]} | {p["part_no"] or ""}')
                qty=c2.number_input(f"Quantity {i+1}",min_value=0.0,key=f"purchaseqty{i}")
                cost=c3.number_input(f"Unit cost {i+1}",min_value=0.0,value=float(product["buy_price"]) if product else 0.0,key=f"purchasecost{i}")
                if product and qty>0: items.append((product,qty,cost))
            paid=st.number_input("Paid now",min_value=0.0,key="purchasepaid")
            submit=st.form_submit_button("Save purchase",type="primary")
        if submit:
            if not items: st.error("Add at least one purchase item.")
            else:
                total=sum(qty*cost for p,qty,cost in items); pay=min(paid,total)
                pid=execute("INSERT INTO purchases(date,party_id,total,paid,account_id) VALUES(?,?,?,?,?)",
                    (purchase_date.isoformat(),supplier["id"] if supplier else None,total,pay,account["id"]))
                for p,qty,cost in items:
                    execute("INSERT INTO purchase_items(purchase_id,product_id,qty,cost) VALUES(?,?,?,?)",(pid,p["id"],qty,cost))
                    execute("UPDATE products SET stock=stock+?,buy_price=? WHERE id=?",(qty,cost,p["id"]))
                if pay:
                    execute("INSERT INTO txns(date,account_id,kind,amount,party_id,ref) VALUES(?,?,?,?,?,?)",
                        (purchase_date.isoformat(),account["id"],"purchase",-pay,supplier["id"] if supplier else None,f"Purchase #{pid}"))
                st.success(f"Purchase #{pid} recorded. Total {money(total)}; paid {money(pay)}."); st.rerun()
    st.subheader("Recent purchases")
    st.dataframe(fmt_table(fetch("SELECT b.id,b.date,p.name supplier,b.total,b.paid,(b.total-b.paid) due FROM purchases b LEFT JOIN parties p ON p.id=b.party_id ORDER BY b.id DESC LIMIT 25")),use_container_width=True,hide_index=True)

elif page=="Customers & Suppliers":
    with st.form("party_form"):
        name=st.text_input("Name *"); phone=st.text_input("Phone"); typ=st.selectbox("Type",["Customer","Supplier"])
        if st.form_submit_button("Add party"):
            if name.strip():
                execute("INSERT INTO parties(name,phone,type) VALUES(?,?,?)",(name,phone,typ.lower()))
                st.success("Added."); st.rerun()
            else: st.error("Name required.")
    rows=[]
    for p in parties():
        rows.append({"Name":p["name"],"Phone":p["phone"],"Type":p["type"].title(),"Due":party_due(p)})
    st.dataframe(rows,use_container_width=True,hide_index=True)
    st.caption("Customer due = customer owes you. Supplier due = you owe supplier.")

elif page=="Money & Accounts":
    accs=accounts(); ps=parties()
    st.subheader("Account balances")
    st.dataframe(fmt_table(account_balances()),use_container_width=True,hide_index=True)
    tab1,tab2,tab3,tab4=st.tabs(["Expense","Transfer","Due payment","Add account"])
    with tab1:
        with st.form("expense"):
            date=st.date_input("Date",dt.date.today(),key="expdate")
            category=st.text_input("Expense category",placeholder="Rent, salary, transport...")
            amount=st.number_input("Amount",min_value=0.01)
            account=st.selectbox("Account",accs,format_func=lambda a:a["name"])
            note=st.text_input("Note")
            if st.form_submit_button("Save expense"):
                execute("INSERT INTO txns(date,account_id,kind,amount,ref,note) VALUES(?,?,?,?,?,?)",(date.isoformat(),account["id"],"expense",-amount,category,note))
                st.success("Expense saved."); st.rerun()
    with tab2:
        with st.form("transfer"):
            date=st.date_input("Transfer date",dt.date.today(),key="transdate")
            frm=st.selectbox("From",accs,format_func=lambda a:a["name"],key="from")
            to=st.selectbox("To",accs,format_func=lambda a:a["name"],key="to")
            amount=st.number_input("Transfer amount",min_value=0.01,key="transamount")
            if st.form_submit_button("Transfer"):
                if frm["id"]==to["id"]: st.error("Select two different accounts.")
                else:
                    execute("INSERT INTO txns(date,account_id,kind,amount,ref) VALUES(?,?,?,?,?)",(date.isoformat(),frm["id"],"transfer",-amount,"Transfer out"))
                    execute("INSERT INTO txns(date,account_id,kind,amount,ref) VALUES(?,?,?,?,?)",(date.isoformat(),to["id"],"transfer",amount,"Transfer in"))
                    st.success("Transfer saved."); st.rerun()
    with tab3:
        with st.form("due_payment"):
            date=st.date_input("Payment date",dt.date.today(),key="due_date")
            party=st.selectbox("Customer or supplier",ps,format_func=lambda p:f'{p["name"]} ({p["type"]}) — due {money(party_due(p))}')
            amount=st.number_input("Amount paid / received",min_value=0.01,key="due_amt")
            account=st.selectbox("Account",accs,format_func=lambda a:a["name"],key="due_account")
            if st.form_submit_button("Record payment"):
                kind="due_in" if party["type"]=="customer" else "due_out"
                signed=amount if party["type"]=="customer" else -amount
                execute("INSERT INTO txns(date,account_id,kind,amount,party_id,ref) VALUES(?,?,?,?,?,?)",(date.isoformat(),account["id"],kind,signed,party["id"],"Due settlement"))
                st.success("Payment recorded."); st.rerun()
    with tab4:
        with st.form("newaccount"):
            accname=st.text_input("Account name")
            opening=st.number_input("Opening balance")
            if st.form_submit_button("Create account"):
                try:
                    execute("INSERT INTO accounts(name,opening) VALUES(?,?)",(accname,opening))
                    st.success("Account created."); st.rerun()
                except sqlite3.IntegrityError: st.error("That account name already exists.")

    st.subheader("Latest transactions")
    st.dataframe(fmt_table(fetch("SELECT t.date,t.kind,t.amount,a.name account,t.ref,t.note FROM txns t LEFT JOIN accounts a ON a.id=t.account_id ORDER BY t.id DESC LIMIT 50")),use_container_width=True,hide_index=True)

elif page=="Reports":
    start=st.date_input("From date",dt.date.today().replace(day=1))
    end=st.date_input("To date",dt.date.today())
    f,t=start.isoformat(),end.isoformat()
    sales=fetchone("SELECT COALESCE(SUM(total),0) v FROM sales WHERE date BETWEEN ? AND ?",(f,t))["v"]
    cogs=fetchone("SELECT COALESCE(SUM(si.qty*si.cost),0) v FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE s.date BETWEEN ? AND ?",(f,t))["v"]
    expenses=fetchone("SELECT COALESCE(SUM(-amount),0) v FROM txns WHERE kind='expense' AND date BETWEEN ? AND ?",(f,t))["v"]
    purchases=fetchone("SELECT COALESCE(SUM(total),0) v FROM purchases WHERE date BETWEEN ? AND ?",(f,t))["v"]
    stockvalue=fetchone("SELECT COALESCE(SUM(stock*buy_price),0) v FROM products")["v"]
    allp=parties(); receivable=sum(party_due(p) for p in allp if p["type"]=="customer"); payable=sum(party_due(p) for p in allp if p["type"]=="supplier")
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Sales",money(sales)); m2.metric("COGS",money(cogs)); m3.metric("Expenses",money(expenses)); m4.metric("Estimated net profit",money(sales-cogs-expenses))
    st.subheader("Summary")
    st.write({"Period":f"{f} to {t}","Purchases":money(purchases),"Inventory value at cost":money(stockvalue),"Customer receivables":money(receivable),"Supplier payables":money(payable),"Account total":money(sum(x["balance"] for x in account_balances()))})
    st.subheader("Sales records")
    st.dataframe(fmt_table(fetch("SELECT s.id,s.date,p.name customer,s.kind,s.total,s.paid,s.total-s.paid due FROM sales s LEFT JOIN parties p ON p.id=s.party_id WHERE s.date BETWEEN ? AND ? ORDER BY s.id DESC",(f,t))),use_container_width=True,hide_index=True)
    st.subheader("Expenses")
    st.dataframe(fmt_table(fetch("SELECT date,ref category,note,amount FROM txns WHERE kind='expense' AND date BETWEEN ? AND ? ORDER BY date DESC",(f,t))),use_container_width=True,hide_index=True)
    st.warning("Profit is an estimate and excludes other adjustments, taxes, returns, payroll, fixed assets and inventory valuation adjustments.")

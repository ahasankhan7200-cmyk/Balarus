import os
import datetime as dt
import io
import zipfile
from contextlib import contextmanager

import pandas as pd
import streamlit as st
import psycopg
from psycopg.rows import dict_row
from psycopg import errors

SHOP = "Balarus Spare House"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(APP_DIR, "assets", "balarus_logo.png")
st.set_page_config(page_title="Balarus Spare House ERP", page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "🚜", layout="wide")
try:
    APP_PASSWORD = st.secrets.get("APP_PASSWORD", os.environ.get("APP_PASSWORD", ""))
    DB_URL = st.secrets.get("DATABASE_URL", os.environ.get("DATABASE_URL", ""))
except Exception:
    APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
    DB_URL = os.environ.get("DATABASE_URL", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
 id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, part_no TEXT, tractor_model TEXT, category TEXT,
 buy_price NUMERIC(14,2) NOT NULL DEFAULT 0, retail_price NUMERIC(14,2) NOT NULL DEFAULT 0,
 wholesale_price NUMERIC(14,2) NOT NULL DEFAULT 0, stock NUMERIC(14,3) NOT NULL DEFAULT 0,
 min_stock NUMERIC(14,3) NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS parties (
 id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, phone TEXT,
 type TEXT NOT NULL CHECK(type IN ('customer','supplier')));
CREATE TABLE IF NOT EXISTS accounts (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, opening NUMERIC(14,2) NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS txns (
 id BIGSERIAL PRIMARY KEY, date TEXT NOT NULL, account_id BIGINT REFERENCES accounts(id), kind TEXT NOT NULL,
 amount NUMERIC(14,2) NOT NULL, party_id BIGINT REFERENCES parties(id), ref TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS sales (
 id BIGSERIAL PRIMARY KEY, date TEXT NOT NULL, party_id BIGINT REFERENCES parties(id), kind TEXT NOT NULL,
 total NUMERIC(14,2) NOT NULL, paid NUMERIC(14,2) NOT NULL DEFAULT 0, account_id BIGINT REFERENCES accounts(id));
CREATE TABLE IF NOT EXISTS sale_items (
 id BIGSERIAL PRIMARY KEY, sale_id BIGINT NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
 product_id BIGINT NOT NULL REFERENCES products(id), qty NUMERIC(14,3) NOT NULL, price NUMERIC(14,2) NOT NULL, cost NUMERIC(14,2) NOT NULL);
CREATE TABLE IF NOT EXISTS purchases (
 id BIGSERIAL PRIMARY KEY, date TEXT NOT NULL, party_id BIGINT REFERENCES parties(id), total NUMERIC(14,2) NOT NULL,
 paid NUMERIC(14,2) NOT NULL DEFAULT 0, account_id BIGINT REFERENCES accounts(id));
CREATE TABLE IF NOT EXISTS purchase_items (
 id BIGSERIAL PRIMARY KEY, purchase_id BIGINT NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
 product_id BIGINT NOT NULL REFERENCES products(id), qty NUMERIC(14,3) NOT NULL, cost NUMERIC(14,2) NOT NULL);
"""

@contextmanager
def db():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL is missing. Configure your PostgreSQL connection in Streamlit Secrets.")
    cn = psycopg.connect(DB_URL, row_factory=dict_row, connect_timeout=15, sslmode="require", prepare_threshold=None)
    try:
        yield cn
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cn.close()

def init_db():
    with db() as cn:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                cn.execute(statement)
        if cn.execute(sql("SELECT COUNT(*) FROM accounts")).fetchone()["count"] == 0:
            cn.executemany(sql("INSERT INTO accounts(name) VALUES(%s)"), [("Cash",), ("Bank",), ("bKash",)])

def sql(q):
    # Existing app queries use SQLite-style placeholders; convert to psycopg placeholders.
    return q.replace("?", "%s")

def fetch(query, params=()):
    with db() as cn:
        return cn.execute(sql(query), params).fetchall()

def fetchone(query, params=()):
    with db() as cn:
        return cn.execute(sql(query), params).fetchone()


def money(value):
    return f"৳{float(value or 0):,.2f}"

def today():
    return dt.date.today().isoformat()

def accounts():
    return fetch("SELECT * FROM accounts ORDER BY id")

def account_balances():
    return fetch("""SELECT a.id, a.name, a.opening+COALESCE(SUM(t.amount),0) AS balance
                  FROM accounts a LEFT JOIN txns t ON t.account_id=a.id
                  GROUP BY a.id ORDER BY a.id""")

def parties(kind=None):
    if kind:
        return fetch("SELECT * FROM parties WHERE type=? ORDER BY name", (kind,))
    return fetch("SELECT * FROM parties ORDER BY name")

def products():
    return fetch("SELECT * FROM products ORDER BY name")

def party_due(p):
    if p["type"] == "customer":
        base = fetchone("SELECT COALESCE(SUM(total-paid),0) n FROM sales WHERE party_id=?", (p["id"],))["n"]
        settlements = fetchone("SELECT COALESCE(SUM(amount),0) n FROM txns WHERE party_id=? AND kind='due_in'", (p["id"],))["n"]
        return max(0.0, float(base-settlements))
    base = fetchone("SELECT COALESCE(SUM(total-paid),0) n FROM purchases WHERE party_id=?", (p["id"],))["n"]
    settlements = fetchone("SELECT COALESCE(SUM(amount),0) n FROM txns WHERE party_id=? AND kind='due_out'", (p["id"],))["n"]
    return max(0.0, float(base+settlements))

def records(rows):
    return [dict(r) for r in rows]

if not DB_URL:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=260)
    st.title(SHOP)
    st.error("DATABASE_URL is not configured. Add it in Streamlit Cloud → App settings → Secrets.")
    st.code('DATABASE_URL = "postgresql://..."\nAPP_PASSWORD = "your-long-password"', language="toml")
    st.stop()

try:
    init_db()
except Exception as exc:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=260)
    st.title(SHOP)
    st.error("Database connection or initialization failed. Check DATABASE_URL and your Supabase connection settings.")
    st.exception(exc)
    st.stop()

# Login: configure APP_PASSWORD in Streamlit secrets or environment variables.
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if not APP_PASSWORD:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=260)
    st.title(SHOP)
    st.error("Login is not configured. Set APP_PASSWORD in Streamlit Cloud → Settings → Secrets, then restart the app.")
    st.code('APP_PASSWORD = "Choose-a-long-unique-password"', language="toml")
    st.stop()
if not st.session_state.authenticated:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=300)
    st.title(SHOP)
    st.subheader("ERP Login")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")
    if submitted:
        if pw == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

with st.sidebar:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, use_container_width=True)
    st.title(SHOP)
    page = st.radio("Navigation", ["Dashboard", "Products & Stock", "Sales", "Purchases", "Customers & Suppliers", "Money & Accounts", "Reports", "Backup"])
    if st.button("Log out"):
        st.session_state.authenticated = False
        st.rerun()
st.title(page)

if page == "Dashboard":
    sales_today = fetchone("SELECT COALESCE(SUM(total),0) n FROM sales WHERE date=?", (today(),))["n"]
    cash_total = sum(float(x["balance"]) for x in account_balances())
    all_parties = parties()
    recv = sum(party_due(p) for p in all_parties if p["type"] == "customer")
    pay = sum(party_due(p) for p in all_parties if p["type"] == "supplier")
    low = fetch("SELECT * FROM products WHERE stock<=min_stock ORDER BY stock")
    a,b,c,d = st.columns(4)
    a.metric("Sales today", money(sales_today)); b.metric("Account balances", money(cash_total))
    c.metric("Customer receivable", money(recv)); d.metric("Supplier payable", money(pay))
    st.subheader("Account balances")
    st.dataframe(records(account_balances()), use_container_width=True, hide_index=True)
    st.subheader("⚠️ Low-stock items")
    st.dataframe(records(low), use_container_width=True, hide_index=True)

elif page == "Products & Stock":
    with st.expander("➕ Add a spare part", expanded=True):
        with st.form("product_add"):
            name = st.text_input("Product name *"); sku = st.text_input("Part number / SKU")
            model = st.text_input("Tractor model"); category = st.text_input("Category")
            a,b,c,d = st.columns(4)
            buy = a.number_input("Purchase price", min_value=0.0); retail = b.number_input("Retail price", min_value=0.0)
            wholesale = c.number_input("Wholesale price", min_value=0.0); stock = d.number_input("Opening stock", min_value=0.0)
            minstock = st.number_input("Minimum stock alert", min_value=0.0)
            save = st.form_submit_button("Save product")
        if save:
            if not name.strip(): st.error("Product name is required.")
            else:
                with db() as cn:
                    cn.execute(sql("INSERT INTO products(name,part_no,tractor_model,category,buy_price,retail_price,wholesale_price,stock,min_stock) VALUES(?,?,?,?,?,?,?,?,?)"), (name.strip(),sku.strip(),model.strip(),category.strip(),buy,retail,wholesale,stock,minstock))
                st.success("Product saved."); st.rerun()
    query = st.text_input("Search product / SKU / model")
    rows = fetch("SELECT * FROM products WHERE name LIKE ? OR part_no LIKE ? OR tractor_model LIKE ? ORDER BY name", (f"%{query}%",)*3)
    st.dataframe(records(rows), use_container_width=True, hide_index=True)
    st.download_button("Download products CSV", pd.DataFrame(records(rows)).to_csv(index=False), "products.csv", "text/csv")

elif page == "Sales":
    prod_list = products(); customers = parties("customer"); accs = accounts()
    if not prod_list: st.warning("Add products first.")
    else:
        pmap = {p["id"]: p for p in prod_list}; amap = {a["id"]: a["name"] for a in accs}; cmap = {p["id"]: p["name"] for p in customers}
        with st.form("sale_form"):
            date = st.date_input("Sale date", dt.date.today()); stype = st.selectbox("Sale type", ["Retail", "Wholesale"])
            customer_id = st.selectbox("Customer (required if credit)", [None]+list(cmap), format_func=lambda x: "Walk-in customer" if x is None else cmap[x])
            account_id = st.selectbox("Receive payment into", list(amap), format_func=lambda x: amap[x])
            st.markdown("**Items (5 lines maximum)**"); items=[]
            for i in range(5):
                x,y,z = st.columns([3,1,1]); pid=x.selectbox(f"Product {i+1}", [None]+list(pmap), key=f"sp{i}", format_func=lambda k: "— Select —" if k is None else f"{pmap[k]['name']} · {pmap[k]['part_no'] or 'no SKU'} · stock {pmap[k]['stock']}")
                qty=y.number_input(f"Qty {i+1}", min_value=0.0, key=f"sq{i}")
                default = (pmap[pid]["retail_price"] if stype=="Retail" else pmap[pid]["wholesale_price"]) if pid else 0.0
                price=z.number_input(f"Unit price {i+1}", min_value=0.0, value=float(default), key=f"sprice{i}")
                if pid and qty>0: items.append((pid,qty,price))
            paid = st.number_input("Received now", min_value=0.0); submit = st.form_submit_button("Save sale", type="primary")
        if submit:
            if not items: st.error("Select products and quantities.")
            else:
                qty_by_product={}
                for pid,qty,price in items: qty_by_product[pid]=qty_by_product.get(pid,0)+qty
                insufficient=[pmap[pid]["name"] for pid,qty in qty_by_product.items() if qty>pmap[pid]["stock"]]
                total=sum(qty*price for _,qty,price in items); payment=min(float(paid),total)
                if insufficient: st.error("Insufficient stock: " + ", ".join(insufficient))
                elif payment<total and customer_id is None: st.error("Choose a customer for a credit sale.")
                else:
                    try:
                        with db() as cn:
                            # Lock selected product rows so concurrent sales cannot oversell stock.
                            locked = cn.execute("SELECT id, stock FROM products WHERE id = ANY(%s) FOR UPDATE", (list(qty_by_product),)).fetchall()
                            current_stock = {r["id"]: float(r["stock"]) for r in locked}
                            still_short = [pmap[pid]["name"] for pid, q in qty_by_product.items() if current_stock.get(pid, 0) < q]
                            if still_short:
                                raise ValueError("Stock changed while saving. Insufficient stock for: " + ", ".join(still_short))
                            cur=cn.execute(sql("INSERT INTO sales(date,party_id,kind,total,paid,account_id) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id"), (date.isoformat(),customer_id,stype.lower(),total,payment,account_id)); sale_id=cur.fetchone()["id"]
                            for pid,qty,price in items:
                                cost=pmap[pid]["buy_price"]
                                cn.execute(sql("INSERT INTO sale_items(sale_id,product_id,qty,price,cost) VALUES(?,?,?,?,?)"), (sale_id,pid,qty,price,cost))
                                cn.execute(sql("UPDATE products SET stock=stock-? WHERE id=?"), (qty,pid))
                            if payment>0: cn.execute(sql("INSERT INTO txns(date,account_id,kind,amount,party_id,ref) VALUES(?,?,?,?,?,?)"), (date.isoformat(),account_id,"sale",payment,customer_id,f"Sale #{sale_id}"))
                        st.success(f"Sale #{sale_id} recorded. Total {money(total)} · Received {money(payment)}"); st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
    st.subheader("Recent sales")
    st.dataframe(records(fetch("SELECT s.id,s.date,p.name customer,s.kind,s.total,s.paid,s.total-s.paid due FROM sales s LEFT JOIN parties p ON p.id=s.party_id ORDER BY s.id DESC LIMIT 30")), use_container_width=True, hide_index=True)

elif page == "Purchases":
    prod_list=products(); suppliers=parties("supplier"); accs=accounts()
    if not prod_list: st.warning("Add products first.")
    else:
        pmap={p["id"]:p for p in prod_list}; amap={a["id"]:a["name"] for a in accs}; smap={p["id"]:p["name"] for p in suppliers}
        with st.form("purchase_form"):
            date=st.date_input("Purchase date",dt.date.today()); supplier_id=st.selectbox("Supplier",[None]+list(smap),format_func=lambda x:"Select supplier (optional)" if x is None else smap[x])
            account_id=st.selectbox("Pay from account",list(amap),format_func=lambda x:amap[x],key="purchase_account")
            items=[]
            for i in range(5):
                x,y,z=st.columns([3,1,1]); pid=x.selectbox(f"Item {i+1}",[None]+list(pmap),key=f"pp{i}",format_func=lambda k:"— Select —" if k is None else f"{pmap[k]['name']} · {pmap[k]['part_no'] or ''}")
                qty=y.number_input(f"Qty {i+1}",min_value=0.0,key=f"pq{i}"); cost=z.number_input(f"Unit cost {i+1}",min_value=0.0,value=float(pmap[pid]["buy_price"]) if pid else 0.0,key=f"pc{i}")
                if pid and qty>0: items.append((pid,qty,cost))
            paid=st.number_input("Paid now",min_value=0.0,key="purchase_paid"); submit=st.form_submit_button("Save purchase",type="primary")
        if submit:
            if not items: st.error("Add at least one purchase item.")
            else:
                total=sum(q*c for _,q,c in items); payment=min(float(paid),total)
                with db() as cn:
                    cur=cn.execute(sql("INSERT INTO purchases(date,party_id,total,paid,account_id) VALUES(%s,%s,%s,%s,%s) RETURNING id"),(date.isoformat(),supplier_id,total,payment,account_id)); purchase_id=cur.fetchone()["id"]
                    for pid,q,cost in items:
                        cn.execute(sql("INSERT INTO purchase_items(purchase_id,product_id,qty,cost) VALUES(?,?,?,?)"),(purchase_id,pid,q,cost))
                        cn.execute(sql("UPDATE products SET stock=stock+?,buy_price=? WHERE id=?"),(q,cost,pid))
                    if payment>0: cn.execute(sql("INSERT INTO txns(date,account_id,kind,amount,party_id,ref) VALUES(?,?,?,?,?,?)"),(date.isoformat(),account_id,"purchase",-payment,supplier_id,f"Purchase #{purchase_id}"))
                st.success(f"Purchase #{purchase_id} saved. Total {money(total)} · Paid {money(payment)}"); st.rerun()
    st.subheader("Recent purchases")
    st.dataframe(records(fetch("SELECT b.id,b.date,p.name supplier,b.total,b.paid,b.total-b.paid due FROM purchases b LEFT JOIN parties p ON p.id=b.party_id ORDER BY b.id DESC LIMIT 30")),use_container_width=True,hide_index=True)

elif page == "Customers & Suppliers":
    with st.form("party_add"):
        name=st.text_input("Name *"); phone=st.text_input("Phone"); kind=st.selectbox("Type",["Customer","Supplier"]); submit=st.form_submit_button("Add")
    if submit:
        if not name.strip(): st.error("Name is required.")
        else:
            with db() as cn: cn.execute(sql("INSERT INTO parties(name,phone,type) VALUES(?,?,?)"),(name.strip(),phone.strip(),kind.lower()))
            st.success("Party added."); st.rerun()
    rows=[{"Name":p["name"],"Phone":p["phone"],"Type":p["type"].title(),"Due":party_due(p)} for p in parties()]
    st.dataframe(rows,use_container_width=True,hide_index=True)
    st.download_button("Download party list CSV",pd.DataFrame(rows).to_csv(index=False),"parties.csv","text/csv")

elif page == "Money & Accounts":
    accs=accounts(); ps=parties(); amap={a["id"]:a["name"] for a in accs}; pmap={p["id"]:p for p in ps}
    st.subheader("Account balances"); st.dataframe(records(account_balances()),use_container_width=True,hide_index=True)
    t1,t2,t3,t4=st.tabs(["Expense","Transfer","Due settlement","Add account"])
    with t1:
        with st.form("expense_form"):
            date=st.date_input("Date",dt.date.today()); category=st.text_input("Category"); amount=st.number_input("Amount",min_value=0.01); aid=st.selectbox("Account",list(amap),format_func=lambda x:amap[x]); note=st.text_input("Note"); submit=st.form_submit_button("Save expense")
        if submit:
            with db() as cn: cn.execute(sql("INSERT INTO txns(date,account_id,kind,amount,ref,note) VALUES(?,?,?,?,?,?)"),(date.isoformat(),aid,"expense",-amount,category,note))
            st.success("Expense saved."); st.rerun()
    with t2:
        with st.form("transfer_form"):
            date=st.date_input("Transfer date",dt.date.today(),key="transferdate"); frm=st.selectbox("From",list(amap),format_func=lambda x:amap[x],key="transferfrom"); to=st.selectbox("To",list(amap),format_func=lambda x:amap[x],key="transferto"); amount=st.number_input("Amount",min_value=0.01,key="transferamount"); submit=st.form_submit_button("Transfer")
        if submit:
            if frm==to: st.error("Choose different accounts.")
            else:
                with db() as cn:
                    cn.execute(sql("INSERT INTO txns(date,account_id,kind,amount,ref) VALUES(?,?,?,?,?)"),(date.isoformat(),frm,"transfer",-amount,"Transfer out"))
                    cn.execute(sql("INSERT INTO txns(date,account_id,kind,amount,ref) VALUES(?,?,?,?,?)"),(date.isoformat(),to,"transfer",amount,"Transfer in"))
                st.success("Transfer saved."); st.rerun()
    with t3:
        if not ps: st.info("Add a customer or supplier first.")
        else:
            with st.form("settlement_form"):
                date=st.date_input("Payment date",dt.date.today(),key="settledate"); party_id=st.selectbox("Party",list(pmap),format_func=lambda x:f"{pmap[x]['name']} ({pmap[x]['type']}) — due {money(party_due(pmap[x]))}"); amount=st.number_input("Amount",min_value=0.01,key="settleamount"); aid=st.selectbox("Account",list(amap),format_func=lambda x:amap[x],key="settleaccount"); submit=st.form_submit_button("Record settlement")
            if submit:
                party=pmap[party_id]; due=party_due(party)
                if amount>due: st.error(f"Amount exceeds current due ({money(due)}).")
                else:
                    kind="due_in" if party["type"]=="customer" else "due_out"; signed=amount if party["type"]=="customer" else -amount
                    with db() as cn: cn.execute(sql("INSERT INTO txns(date,account_id,kind,amount,party_id,ref) VALUES(?,?,?,?,?,?)"),(date.isoformat(),aid,kind,signed,party_id,"Due settlement"))
                    st.success("Settlement saved."); st.rerun()
    with t4:
        with st.form("account_add"):
            name=st.text_input("Account name"); opening=st.number_input("Opening balance",value=0.0); submit=st.form_submit_button("Create account")
        if submit:
            try:
                with db() as cn: cn.execute(sql("INSERT INTO accounts(name,opening) VALUES(?,?)"),(name.strip(),opening))
                st.success("Account created."); st.rerun()
            except errors.UniqueViolation: st.error("Account name already exists.")
    st.subheader("Recent transactions")
    st.dataframe(records(fetch("SELECT t.date,t.kind,t.amount,a.name account,t.ref,t.note FROM txns t LEFT JOIN accounts a ON a.id=t.account_id ORDER BY t.id DESC LIMIT 100")),use_container_width=True,hide_index=True)

elif page == "Reports":
    start=st.date_input("From",dt.date.today().replace(day=1)); end=st.date_input("To",dt.date.today()); f,t=start.isoformat(),end.isoformat()
    if start>end: st.error("Start date must be on or before end date.")
    else:
        sales=fetchone("SELECT COALESCE(SUM(total),0) v FROM sales WHERE date BETWEEN ? AND ?",(f,t))["v"]
        cogs=fetchone("SELECT COALESCE(SUM(si.qty*si.cost),0) v FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE s.date BETWEEN ? AND ?",(f,t))["v"]
        expenses=fetchone("SELECT COALESCE(SUM(-amount),0) v FROM txns WHERE kind='expense' AND date BETWEEN ? AND ?",(f,t))["v"]
        purchase_total=fetchone("SELECT COALESCE(SUM(total),0) v FROM purchases WHERE date BETWEEN ? AND ?",(f,t))["v"]
        stock_value=fetchone("SELECT COALESCE(SUM(stock*buy_price),0) v FROM products")["v"]
        allp=parties(); recv=sum(party_due(p) for p in allp if p["type"]=="customer"); payable=sum(party_due(p) for p in allp if p["type"]=="supplier")
        a,b,c,d=st.columns(4); a.metric("Sales",money(sales)); b.metric("COGS",money(cogs)); c.metric("Expenses",money(expenses)); d.metric("Estimated profit",money(sales-cogs-expenses))
        st.write({"Period":f"{f} to {t}","Purchases":money(purchase_total),"Stock value at cost":money(stock_value),"Receivables":money(recv),"Payables":money(payable),"Account total":money(sum(x["balance"] for x in account_balances()))})
        st.subheader("Sales in period"); sales_rows=fetch("SELECT s.id,s.date,p.name customer,s.kind,s.total,s.paid,s.total-s.paid due FROM sales s LEFT JOIN parties p ON p.id=s.party_id WHERE s.date BETWEEN ? AND ? ORDER BY s.id DESC",(f,t)); st.dataframe(records(sales_rows),use_container_width=True,hide_index=True)
        st.download_button("Export sales CSV",pd.DataFrame(records(sales_rows)).to_csv(index=False),"sales_report.csv","text/csv")
        st.subheader("Expenses"); exp_rows=fetch("SELECT date,ref category,note,amount FROM txns WHERE kind='expense' AND date BETWEEN ? AND ? ORDER BY date DESC",(f,t)); st.dataframe(records(exp_rows),use_container_width=True,hide_index=True)
        st.warning("Profit is an estimate. It excludes tax, returns, payroll, fixed assets and stock adjustments. This is not a formal accounting statement.")

elif page == "Backup":
    st.warning("This backup exports your business tables as CSV files in a ZIP. Store it securely; it contains confidential business data.")
    tables = ["products", "parties", "accounts", "txns", "sales", "sale_items", "purchases", "purchase_items"]
    if st.button("Prepare backup ZIP", type="primary"):
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as archive:
            for table in tables:
                data = pd.DataFrame(records(fetch(f"SELECT * FROM {table} ORDER BY id"))).to_csv(index=False)
                archive.writestr(f"{table}.csv", data)
        st.download_button("Download backup ZIP", mem.getvalue(), f"balarus_backup_{today()}.zip", "application/zip")
    st.caption("Your data is stored in hosted PostgreSQL and is not tied to this app's local filesystem.")

import os, sqlite3
from dotenv import load_dotenv

load_dotenv()
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autopay.db")


def conn():
    c = sqlite3.connect(PATH)
    c.row_factory = sqlite3.Row
    return c


SEED = [
    (1,  "Aarav Mehta",   1499, "Card expired",             "2026-09-28", "Pro Plan",      "452001", "Cooperative. Agrees to pay now.",                          "shreyash3087@gmail.com"),
    (2,  "Priya Nair",     799, "Insufficient balance",     "2026-09-29", "Basic Plan",    "462001", "Busy. Promises to pay on Friday.",                         "shreyash3087@gmail.com"),
    (3,  "Rohan Gupta",   2499, "Bank declined the charge", "2026-09-27", "Premium Plan",  "400001", "Disputes it. Says he cancelled last month.",               "shreyash3087@gmail.com"),
    (4,  "Sneha Iyer",     499, "UPI mandate failed",       "2026-09-30", "Starter Plan",  "110001", "Confused. Asks many questions, then pays.",                "shreyash3087@gmail.com"),
    (5,  "Vikram Singh",  1999, "Card expired",             "2026-09-26", "Pro Plan",      "560001", "Angry. Demands a human.",                                  "shreyash3087@gmail.com"),
    (6,  "Ananya Das",     999, "Insufficient balance",     "2026-09-29", "Basic Plan",    "600001", "Gives a wrong postal code twice.",                         "shreyash3087@gmail.com"),
    (7,  "Karthik Reddy", 3499, "Bank declined the charge", "2026-09-25", "Business Plan", "500001", "Says call me later, then asks to stop calls.",             "shreyash3087@gmail.com"),
    (8,  "Meera Joshi",    649, "UPI mandate failed",       "2026-10-01", "Starter Plan",  "411001", "Cannot pay today. Promises a date next week.",             "shreyash3087@gmail.com"),
    (9,  "Imran Khan",    1299, "Card expired",             "2026-09-28", "Pro Plan",      "700001", "Does not pick up. Use this to test no answer and retry.", "shreyash3087@gmail.com"),
    (10, "Divya Menon",    899, "Insufficient balance",     "2026-09-30", "Basic Plan",    "380001", "Asks if this is a scam, then cooperates.",                 "shreyash3087@gmail.com"),
]


def init(reset=False):
    phone = os.getenv("DEMO_PHONE", "+910000000000")
    demo_email = os.getenv("DEMO_EMAIL", "")
    with conn() as c:
        if reset:
            c.execute("drop table if exists customers")
        c.execute(
            """create table if not exists customers(
            id integer primary key, name text, phone text, email text default '', amount integer, reason text, due text,
            plan text, postal text, persona text, status text default 'active', attempts integer default 0,
            promised_date text default '', notes text default '', pay_link text default '', dnc integer default 0)"""
        )
        cols = [col[1] for col in c.execute("pragma table_info(customers)").fetchall()]
        if "email" not in cols:
            c.execute("alter table customers add column email text default ''")
        if c.execute("select count(*) from customers").fetchone()[0] == 0:
            c.executemany(
                "insert into customers(id,name,amount,reason,due,plan,postal,persona,email,phone,status) values(?,?,?,?,?,?,?,?,?,?,'active')",
                [(*row[:-1], demo_email or row[-1], phone) for row in SEED],
            )
        else:
            for row in SEED:
                cid = row[0]
                em = os.getenv("DEMO_EMAIL", row[-1])
                c.execute("update customers set email=? where id=?", (em, cid))

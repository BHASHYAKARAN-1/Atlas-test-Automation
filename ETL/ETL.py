import os
import time
import traceback
import webbrowser
from datetime import datetime

import pandas as pd
import pyodbc


# ==========================================================
# CONFIGURATION
# ==========================================================

SERVER = "tcp:54.202.110.163,1433"
DATABASE = "Atlas"
USERNAME = "atlas;"
PASSWORD = "!atlas!!*;"



PROVIDER_NAME = "Maine: Exclusions"
PROCEDURE_NAME = "MaineExclusions"

# provider_name = "FDA Debarment"
# procedure_name = "FDADebarment"


status = "PASS"
error_message = ""
provider_id = "N/A"
job_id = "N/A"
cert_df = pd.DataFrame()


# ==========================================================
# DATABASE
# ==========================================================
def get_provider(conn, provider_name):

    provider_df = pd.read_sql("""
        SELECT TOP 1
            Id,
            Name,
            PersistentId
        FROM CertificationProviders
        WHERE LOWER(Name) LIKE LOWER(?)
    """, conn, params=[f"%{provider_name}%"])

    if provider_df.empty:
        raise Exception(f"{provider_name} not found")

    provider_id = int(provider_df.iloc[0]["Id"])

    return provider_id, provider_df 
def get_job(conn, procedure_name):

    job_df = pd.read_sql("""
        SELECT TOP 1
            *
        FROM CertificationProviderJobs
        WHERE LOWER(ProcedureName) LIKE LOWER(?)
    """, conn, params=[f"%{procedure_name}%"])

    if job_df.empty:
        raise Exception(f"{procedure_name} not found")

    job_id = int(job_df.iloc[0]["Id"])

    return job_id, job_df
def connect_database():

    try:
        conn = pyodbc.connect(
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            f"UID={USERNAME};"
            f"PWD={PASSWORD};"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
            "MARS_Connection=yes;"
            "Pooling=no;",
            timeout=30,
        )

        print("=" * 80)
        print("Database Connected Successfully")

        return conn, conn.cursor()

    except Exception as e:
        print("=" * 80)
        print("Database Connection Failed")
        raise Exception(f"Unable to connect to SQL Server: {e}")
def cleanup(cursor, conn, provider_id, job_id):

    print("=" * 80)
    print("Deleting Existing Data...")

    # Delete CertificationRequestResults
    cursor.execute("""
        DELETE FROM CertificationRequestResults
        WHERE CertificationId IN
        (
            SELECT Id
            FROM Certifications
            WHERE ProviderId = ?
        )
    """, provider_id)

    # Delete Certifications
    cursor.execute("""
        DELETE FROM Certifications
        WHERE ProviderId = ?
    """, provider_id)

    # Delete Job Logs
    cursor.execute("""
        DELETE FROM CertificationProviderJobLogs
        WHERE CertificationProviderJobId = ?
    """, job_id)

    conn.commit()

    print("Cleanup Completed")    
def update_frequency(cursor, conn, job_id, frequency):
    cursor.execute("""
        UPDATE CertificationProviderJobs
        SET Frequency = ?
        WHERE Id = ?
    """, frequency, job_id)

    conn.commit()

    print(f"Frequency updated to {frequency}")

def wait_for_job(conn, job_id):

    print("=" * 80)
    print("Waiting for ETL job...")

    while True:

        df = pd.read_sql("""
            SELECT Success
            FROM CertificationProviderJobLogs
            WHERE CertificationProviderJobId = ?
            ORDER BY Id DESC
        """, conn, params=[job_id])

        if df.empty:
            print("Logs not processed in DB yet. Waiting...")
            time.sleep(10)
            continue

        statuses = df["Success"].tolist()
        print("Current Statuses:", statuses)

        if 3 in statuses:
            print("Job Started...")

        if any(x in (1, 2) for x in statuses):
            print("File downloaded in server.")
            print("Job Completed Successfully.")
            return

        time.sleep(10)

def wait_for_data(conn, provider_id, timeout=300):
    print("=" * 80)
    print("Waiting for Certification data...")

    start_time = time.time()

    while time.time() - start_time < timeout:

        cert_df = pd.read_sql("""
            SELECT *
            FROM Certifications
            WHERE ProviderId = ?
            ORDER BY Id DESC
        """, conn, params=[provider_id])

        if not cert_df.empty:
            print("=" * 80)
            print(f"TOTAL ROWS DOWNLOADED: {len(cert_df)}")
            print(cert_df.head(2))
            return cert_df

        elapsed = int(time.time() - start_time)
        print(f"File not processed yet. Waited {elapsed}s/{timeout}s...")
        time.sleep(10)

    raise TimeoutError(f"No certification data found after {timeout} seconds.")

def get_logs(conn, job_id):
    while True:
        logs_df = pd.read_sql("""
            SELECT TOP 2 *
            FROM CertificationProviderJobLogs
            WHERE CertificationProviderJobId = ?
            ORDER BY Id DESC
        """, conn, params=[job_id])

        if not logs_df.empty:
            print("=" * 80)
            print(f"Found {len(logs_df)} log(s).")
            print(logs_df)
            return logs_df

        print("No logs found yet. Waiting 30 seconds...")
        time.sleep(30)

def get_certifications(conn, provider_id):

    cert_df = pd.read_sql("""
        SELECT *
        FROM Certifications
        WHERE ProviderId = ?
        ORDER BY Id DESC
    """, conn, params=[provider_id])

    print("=" * 80)
    print(f"TOTAL ROWS DOWNLOADED : {len(cert_df)}")

    print("=" * 80)
    print("TOP 2 CERTIFICATION RECORDS")
    print(cert_df.head(2))

    return cert_df

def generate_report(provider_name, procedure_name,
                    provider_id, job_id,
                    cert_df,
                    status,
                    error_message,
                    execution_time):

    os.makedirs("Reports", exist_ok=True)

    report = os.path.join(
        "Reports",
        f"Execution_Report_{datetime.now():%Y%m%d_%H%M%S}.html"
    )

    records = len(cert_df)

    color = "green" if status == "PASS" else "red"

    html = f"""
    <html>
    <body style='font-family:Arial'>
    <h2>Atlas ETL Execution Report</h2>
    <table border=1 cellpadding=8 cellspacing=0>
    <tr><th>Item</th><th>Value</th></tr>
    <tr><td>Status</td><td style='color:{color}'>{status}</td></tr>
    <tr><td>Provider</td><td>{provider_name}</td></tr>
    <tr><td>Procedure</td><td>{procedure_name}</td></tr>
    <tr><td>Provider ID</td><td>{provider_id}</td></tr>
    <tr><td>Job ID</td><td>{job_id}</td></tr>
    <tr><td>Total Records</td><td>{records}</td></tr>
    <tr><td>Execution Time</td><td>{execution_time} sec</td></tr>
    <tr><td>Error</td><td>{error_message or "None"}</td></tr>
    </table>
    </body>
    </html>
    """

    with open(report, "w", encoding="utf-8") as f:
        f.write(html)

    webbrowser.open(os.path.abspath(report))


def main():
    global status, error_message, provider_id, job_id, cert_df

    start = time.time()

    conn = None
    cursor = None

    try:
        conn, cursor = connect_database()

        provider_id, provider_df = get_provider(conn, PROVIDER_NAME)
        print(provider_df)

        job_id, job_df = get_job(conn, PROCEDURE_NAME)
        print(job_df.head())

        cleanup(cursor, conn, provider_id, job_id)
        print("Cleanup completed")

        update_frequency(cursor, conn, job_id, 5)
        print("Frequency updated to 5")

        wait_for_job(conn, job_id)

        wait_for_data(conn, provider_id)

        print(get_logs(conn, job_id))

        cert_df = get_certifications(conn, provider_id)

        print(cert_df.head(2))

        update_frequency(cursor, conn, job_id, 6)
        print("Frequency reset to 6")

    except Exception as e:
        status = "FAIL"
        error_message = str(e)
        traceback.print_exc()

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

        generate_report(
            PROVIDER_NAME,
            PROCEDURE_NAME,
            provider_id,
            job_id,
            cert_df,
            status,
            error_message,
            round(time.time() - start, 2),
        )


if __name__ == "__main__":
    main()

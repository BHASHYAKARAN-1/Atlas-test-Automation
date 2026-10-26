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

# SERVER = "tcp:184.33.25.205,1433"
# DATABASE = "Atlas"
# USERNAME = "engine;"
# PASSWORD = "UtORVqu7WDLNJ*"




# PROVIDER_NAME = "Maine: Exclusions"
# PROCEDURE_NAME = "MaineExclusions"


#PROVIDER_NAME = "SAM: Exclusions"
#PROCEDURE_NAME = "SAMImport"


 provider_name = "FDA Debarment"
procedure_name = "FDADebarment"

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
    time.sleep(10)
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
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT COUNT(*)
                FROM Certifications
                WHERE ProviderId = ?
            """, provider_id)

            total_count = cursor.fetchone()[0]

        finally:
            cursor.close()

        if total_count > 0:
            print("=" * 80)
            print(f"TOTAL CERTIFICATION RECORDS: {total_count}")
            print("Certification data is available.")
            return total_count

        elapsed = int(time.time() - start_time)
        print(f"No certification data yet. Waited {elapsed}s/{timeout}s...")
        time.sleep(5)

    raise TimeoutError(
        f"No certification data found for provider {provider_id} "
        f"after {timeout} seconds."
    )

def get_logs(conn, job_id):
    while True:
        time.sleep(15)
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
    print("=" * 80)
    print("Fetching final Certification count...")

    cursor = conn.cursor()

    try:
        # Get total count
        cursor.execute("""
            SELECT COUNT(*)
            FROM Certifications
            WHERE ProviderId = ?
        """, provider_id)

        total_count = cursor.fetchone()[0]

        # Get first 2 records
        cursor.execute("""
            SELECT TOP 2 *
            FROM Certifications
            WHERE ProviderId = ?
            ORDER BY Id DESC
        """, provider_id)

        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        cert_df = pd.DataFrame.from_records(rows, columns=columns)

        print(f"TOTAL CERTIFICATION RECORDS: {total_count}")
        print("TOP 2 CERTIFICATION RECORDS:")
        print(cert_df)

        return total_count, cert_df

    finally:
        cursor.close()

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

    records = cert_df.attrs.get("total_count", len(cert_df))

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
        # Connect to database
        conn, cursor = connect_database()

        # Get provider details
        provider_id, provider_df = get_provider(conn, PROVIDER_NAME)
        print(provider_df)

        # Get job details
        job_id, job_df = get_job(conn, PROCEDURE_NAME)
        print(job_df.head())

        # Cleanup existing data and logs
        cleanup(cursor, conn, provider_id, job_id)
        print("Cleanup completed")

        # Update frequency to trigger ETL
        update_frequency(cursor, conn, job_id, 5)
        print("Frequency updated to 5")

        # Wait for ETL job completion
        wait_for_job(conn, job_id)

        # Wait for certification data
        data_count = wait_for_data(conn, provider_id)
        print(f"Certification count confirmed: {data_count}")

        # Fetch job logs
        logs_df = get_logs(conn, job_id)
        print(logs_df)

        # Get total certification count and first 2 records
        cert_count, cert_df = get_certifications(conn, provider_id)

        # Preserve total count for HTML report
        cert_df.attrs["total_count"] = cert_count

        print("=" * 80)
        print(f"TOTAL CERTIFICATION RECORDS: {cert_count}")
        print("FIRST 2 CERTIFICATION RECORDS:")
        print(cert_df.head(2))

        # Reset frequency
        update_frequency(cursor, conn, job_id, 6)
        print("Frequency reset to 6")

        status = "PASS"

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


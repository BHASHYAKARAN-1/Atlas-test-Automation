import os
import webbrowser
import traceback
from datetime import datetime
import time
import pandas as pd
from pathlib import Path
status="PASS"
error_message=""
start_time=time.time()
provider_id="N/A"
job_id="N/A"
cert_df=pd.DataFrame()

try:

    import pyodbc
    import pandas as pd
    import time

    # ==========================================
    # DATABASE CONNECTION
    # ==========================================

    conn = pyodbc.connect(
          "DRIVER={ODBC Driver 17 for SQL Server};"
          "SERVER=tcp:54.202.110.163,1433;"
          "DATABASE=Atlas;"
          "UID=atlas;"
          "PWD=!atlas!!*;"
          "Encrypt=yes;"
          "TrustServerCertificate=yes;"
          "MARS_Connection=yes;"
          "Pooling=no;",
          timeout=30
      )

    cursor = conn.cursor()

    # ==========================================
    # USER INPUT
    # ==========================================


    provider_name = "FDA Debarment"
    procedure_name = "FDADebarment"

    # ==========================================
    # GET PROVIDER ID
    # ==========================================

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
    persistent_id = provider_df.iloc[0]["PersistentId"]

    print("=" * 80)
    print("PROVIDER DETAILS")
    print(provider_df)

    # ==========================================
    # GET JOB ID
    # ==========================================

    job_df = pd.read_sql("""
    SELECT TOP 1 *
    FROM CertificationProviderJobs
    WHERE LOWER(ProcedureName) LIKE LOWER(?)
    """, conn, params=[f"%{procedure_name}%"])

    if job_df.empty:
        raise Exception(f"{procedure_name} not found")

    job_id = int(job_df.iloc[0]["Id"])

    print("=" * 80)
    print("JOB DETAILS")
    print(job_df.head(1))

    # ==========================================
    # DELETE OLD DATA
    # ==========================================

    print("=" * 80)
    print("Deleting Existing Data...")

    cursor.execute("""
    DELETE FROM CertificationRequestResults
    WHERE CertificationId IN
    (
        SELECT Id
        FROM Certifications
        WHERE ProviderId = ?
    )
    """, provider_id)

    cursor.execute("""
    DELETE FROM Certifications
    WHERE ProviderId = ?
    """, provider_id)

    cursor.execute("""
    DELETE FROM CertificationProviderJobLogs
    WHERE CertificationProviderJobId = ?
    """, job_id)

    conn.commit()

    print("Cleanup Completed")

    # ==========================================
    # UPDATE FREQUENCY TO 5
    # ==========================================

    cursor.execute("""
    UPDATE CertificationProviderJobs
    SET Frequency = 5
    WHERE Id = ?
    """, job_id)

    conn.commit()

    print("Frequency Updated To 5")

    # ==========================================
    # WAIT FOR SUCCESS = 3 THEN 1
    # ==========================================

    print("=" * 80)
    print("Waiting For Job Execution...")

    found_3 = False

    while True:

        logs_df = pd.read_sql("""
        SELECT TOP 10 *
        FROM CertificationProviderJobLogs
        WHERE CertificationProviderJobId = ?
        ORDER BY Id DESC
        """, conn, params=[job_id])

        if logs_df.empty:
            print("No logs yet...")
            time.sleep(10)
            continue

        success_values = logs_df["Success"].tolist()

        print("Current Success Values:", success_values)

        # First wait for 3

        if not found_3 and 3 in success_values:
            found_3 = True
            print("SUCCESS = 3 FOUND")

        # Then wait for 1

        if found_3 and 1 in success_values:
            print("SUCCESS = 1 FOUND")
            print("Job Completed")
            break

        time.sleep(10)

    # ==========================================
    # PRINT LAST 2 LOG ROWS
    # ==========================================

    latest_logs = pd.read_sql("""
    SELECT TOP 2 *
    FROM CertificationProviderJobLogs
    WHERE CertificationProviderJobId = ?
    ORDER BY Id DESC
    """, conn, params=[job_id])

    print("=" * 80)
    print("LATEST 2 LOG RECORDS")
    print(latest_logs)

    # ==========================================
    # VERIFY CERTIFICATION DATA
    # ==========================================

    cert_df = pd.read_sql("""
    SELECT *
    FROM Certifications
    WHERE ProviderId = ?
    ORDER BY Id DESC
    """, conn, params=[provider_id])

    print("=" * 80)
    print(f"TOTAL ROWS DOWNLOADED : {len(cert_df)}")

    # Print first 2 downloaded records

    print("=" * 80)
    print("TOP 2 CERTIFICATION RECORDS")

    print(cert_df.head(2))

    # ==========================================
    # RESET FREQUENCY TO 6
    # ==========================================

    cursor.execute("""
    UPDATE CertificationProviderJobs
    SET Frequency = 6
    WHERE Id = ?
    """, job_id)

    conn.commit()

    print("=" * 80)
    print("Frequency Reset To 6")

    # ==========================================
    # CLOSE CONNECTION
    # ==========================================

    cursor.close()
    conn.close()

    print("=" * 80)
    print("EXECUTION COMPLETED SUCCESSFULLY")

except Exception as e:
    status="FAIL"
    error_message=str(e)
    traceback.print_exc()

finally:
    execution_time = round(time.time() - start_time, 2)

    try:
        os.makedirs("Reports", exist_ok=True)

        report = os.path.join(
            "Reports",
            f"Execution_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        )

        records = len(cert_df) if not cert_df.empty else 0

        color = "green" if status == "PASS" else "red"
        icon = "PASS ✅" if status == "PASS" else "FAIL ❌"

        html = f"""
                <html>
                <head>
                    <title>Atlas ETL Execution Report</title>
                </head>
                <body style="font-family:Arial">

                <h2>Atlas ETL Execution Summary</h2>

                <table border="1" cellspacing="0" cellpadding="8">
                <tr><th>Item</th><th>Value</th></tr>

                <tr><td>Status</td><td style="color:{color}"><b>{icon}</b></td></tr>
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

        print("Report created:", os.path.abspath(report))
        webbrowser.open(os.path.abspath(report))

    except Exception as e:
        print("Report generation failed:", e)
        traceback.print_exc()

    try:
        cursor.close()
    except:
        pass

    try:
        conn.close()
    except:
        pass

# Auth for GEE

To authenticate the Google Earth Engine (GEE) Python API using an API key, you can configure your environment to use a service account instead of manual authentication. This involves generating a service account in the Google Cloud Console, assigning it an API key, and linking it to your Earth Engine project.

Here’s how to do it step-by-step:

### Step 1: Enable Earth Engine API in Google Cloud Console

    - Go to the Google Cloud Console.
    - Create a project (or use an existing one).
    - Enable the Earth Engine API for your project:
        - Navigate to APIs & Services > Library.
        - Search for "Earth Engine API" and enable it.

### Step 2: Create a Service Account

    - Navigate to APIs & Services > Credentials in the Cloud Console.
    - Click Create Credentials and select Service Account.
    - Fill in the required fields, then click Create.
    - Assign the "Editor" role (or other roles as required).
    - Download the JSON key file for the service account.

### Step 3: Grant the Service Account Access to Earth Engine

    - Go to the Earth Engine Service Account Permissions.
    - Add the email of the service account (e.g., my-service-account@project-id.iam.gserviceaccount.com) under Manage Permissions.
    - Assign it the desired role, typically "Can Edit" or "Can View".
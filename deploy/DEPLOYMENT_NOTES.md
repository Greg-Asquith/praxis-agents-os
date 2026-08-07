# DEPLOYMENT FEEDBACK NOTES

---

## Confirmation messages look confusing inline

== API enablement will run exactly these commands ==
  gcloud services enable run.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable sqladmin.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable secretmanager.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable artifactregistry.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable cloudscheduler.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable iamcredentials.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable iam.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable sts.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable logging.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable monitoring.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable storage.googleapis.com --project=praxis-agents-os --quiet 
  gcloud services enable containerscanning.googleapis.com --project=praxis-agents-os --quiet 
Type yes to authorize API enablement: yes
+ gcloud services enable run.googleapis.com --project=praxis-agents-os --quiet 
Operation "operations/acf.p2-968065341846-43380a08-10a6-4a91-bd38-77e61b7161b8" finished successfully.
+ gcloud services enable sqladmin.googleapis.com --project=praxis-agents-os --quiet 
Operation "operations/acat.p2-968065341846-ef709da2-7cc9-4ee2-a051-84efc0dcb0c8" finished successfully.
+ gcloud services enable secretmanager.googleapis.com --project=praxis-agents-os --quiet 
+ gcloud services enable artifactregistry.googleapis.com --project=praxis-agents-os --quiet 
+ gcloud services enable cloudscheduler.googleapis.com --project=praxis-agents-os --quiet 
Operation "operations/acf.p2-968065341846-0ff45b00-1930-46b0-b582-776f80ea2510" finished successfully.
+ gcloud services enable iamcredentials.googleapis.com --project=praxis-agents-os --quiet 
Operation "operations/acat.p2-968065341846-25676d49-9c43-4725-a092-91495f96ce48" finished successfully.
+ gcloud services enable iam.googleapis.com --project=praxis-agents-os --quiet 
Operation "operations/acat.p2-968065341846-a543227b-4c8c-48f8-a745-0b8804e34ecd" finished successfully.
+ gcloud services enable sts.googleapis.com --project=praxis-agents-os --quiet 
Operation "operations/acat.p2-968065341846-3902e4d2-e498-4844-aa44-e8583b464e24" finished successfully.
+ gcloud services enable logging.googleapis.com --project=praxis-agents-os --quiet 
+ gcloud services enable monitoring.googleapis.com --project=praxis-agents-os --quiet 
+ gcloud services enable storage.googleapis.com --project=praxis-agents-os --quiet 
+ gcloud services enable containerscanning.googleapis.com --project=praxis-agents-os --quiet 
Operation "operations/acf.p2-968065341846-77bfc5e1-48c2-478b-9312-f595b2c34f6e" finished successfully.

---

## SQL Warnings

== Cloud SQL runtime user roles will run exactly these commands ==
  gcloud sql users assign-roles praxis_app --instance=praxis-staging-postgres --type=BUILT_IN --database-roles= --revoke-existing-roles --project=praxis-agents-os --quiet 
Type yes to authorize Cloud SQL runtime user roles: yes
+ gcloud sql users assign-roles praxis_app --instance=praxis-staging-postgres --type=BUILT_IN --database-roles= --revoke-existing-roles --project=praxis-agents-os --quiet 
Updating Cloud SQL user...done.                                                
WARNING: The following filter keys were not present in any resource : state
WARNING: The following filter keys were not present in any resource : state

---

## IAM Warning

version: 1
+ gcloud projects add-iam-policy-binding praxis-agents-os --member=serviceAccount:praxis-staging-api@praxis-agents-os.iam.gserviceaccount.com --role=projects/praxis-agents-os/roles/praxisSecretManager --condition=expression=\(resource.type\ ==\ \'secretmanager.googleapis.com/Secret\'\ \|\|\ resource.type\ ==\ \'secretmanager.googleapis.com/SecretVersion\'\)\ \&\&\ resource.name.startsWith\(\'projects/968065341846/secrets/praxis-\'\)\,title=Praxis\ application\ secret\ namespace\,description=Manage\ only\ application-owned\ Praxis\ secrets --quiet 
WARNING: Adding binding with condition to a policy with

---



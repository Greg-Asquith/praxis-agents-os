# Register Microsoft Entra applications

Praxis uses a separate Microsoft Entra application for Outlook Mail, Outlook
Calendar, and SharePoint. It also keeps these applications separate from the
Microsoft application used for login single sign-on (SSO). This separation
lets you add or remove one Microsoft service without changing the others.

## Register applications with the script

Use the repository script when you can run the Azure CLI. You need Azure CLI
2.77.0 or later, Python 3, and a tenant role that can manage applications and
grant administrator consent.

1. Sign in to the tenant that owns the applications:

   ```bash
   az login --tenant YOUR_TENANT_ID
   ```

2. Register the services you plan to enable. Set `--redirect-uri` to the exact
   `INTEGRATIONS_OAUTH_REDIRECT_URI` value:

   ```bash
   deploy/entra/register-apps.sh \
     --redirect-uri https://api.example.com/integrations/oauth/callback \
     --outlook-mail \
     --outlook-calendar \
     --sharepoint
   ```

   The script shows every proposed change and waits for you to type `yes`. It
   creates a 12-month client secret only when an application has no active
   secret. Use `--secret-months N` to select a lifetime from 1 to 24 months.
   The secret appears once in the terminal and isn't written to disk.

3. Store each printed client ID and secret in the deployment's secret manager.
   Store the printed `MICROSOFT_GRAPH_TENANT` value with the application
   settings. Leave each service's `*_OAUTH_TENANT` blank unless that application
   belongs to a different tenant.

4. Add the selected provider keys to `INTEGRATIONS_ENABLED_PROVIDERS`. The keys
   are `outlook_mail`, `outlook_calendar`, and `sharepoint`.

5. Record each client secret's expiry date in your operations calendar.

The script sets each application's permissions to the service's exact declared
set. A second run compares the application before making changes. When you add
a permission, rerun the script, grant consent, and deploy the matching code.
Existing connections receive the permission on token refresh.

### Optional: restrict who can connect

To keep unassigned or guest accounts from connecting, turn on **Assignment
required** for each enterprise application and assign the allowed people or
groups. If sign-in reports an approval or assignment problem, ask the tenant
administrator to finish this configuration.

Conditional Access policies continue to apply to each application.

## Register applications for several organizations

For a hosted deployment that serves several Microsoft Entra organizations, add
`--multi-tenant` to the registration command. The script sets
`MICROSOFT_GRAPH_TENANT=organizations` and doesn't grant consent in the
operator's tenant.

Complete publisher verification before offering the applications to another
organization. Then send each customer's administrator a consent URL for each
application:

```text
https://login.microsoftonline.com/organizations/v2.0/adminconsent?client_id=CLIENT_ID&scope=SCOPES&redirect_uri=REDIRECT_URI
```

Replace `SCOPES` with that application's space-separated scope set. The callback
confirms successful administrator consent and directs the administrator back to
the integrations page. Praxis never uses a callback `tenant` parameter as an
identity claim.

## Optional: register applications in the Entra admin center

If you can't run the Azure CLI, create one application for each service in the
Microsoft Entra admin center.

1. In **Identity > Applications > App registrations**, click **New
   registration**.

2. Name the application `Praxis Agents — Outlook Mail`, `Praxis Agents —
   Outlook Calendar`, or `Praxis Agents — SharePoint`.

3. For a single-tenant deployment, select **Accounts in this organizational
   directory only**. For a hosted multi-tenant deployment, select **Accounts in
   any organizational directory**.

4. Under **Redirect URI**, select **Web** and enter the exact
   `INTEGRATIONS_OAUTH_REDIRECT_URI` value.

5. Under **API permissions**, add only the selected application's delegated
   Microsoft Graph permissions:

   - Outlook Mail: `openid`, `profile`, `email`, `offline_access`, `User.Read`,
     `Mail.ReadWrite`, `Mail.Send`, `MailboxSettings.Read`, and `People.Read`.
   - Outlook Calendar: `openid`, `profile`, `email`, `offline_access`,
     `User.Read`, `Calendars.ReadWrite`, `Calendars.Read.Shared`,
     `MailboxSettings.Read`, and `People.Read`.
   - SharePoint: `openid`, `profile`, `email`, `offline_access`, `User.Read`,
     `Files.Read.All`, and `Sites.Read.All`.

6. For a single-tenant deployment, click **Grant admin consent for
   TENANT_NAME**.

7. Under **Certificates & secrets**, create a client secret and store its value
   immediately. Entra doesn't show the value again.

8. Copy the application ID and secret into the matching
   `<PREFIX>_OAUTH_CLIENT_ID` and `<PREFIX>_OAUTH_CLIENT_SECRET` settings. Set
   `MICROSOFT_GRAPH_TENANT` to the tenant ID, verified domain, or
   `organizations`.

To remove access outside Praxis, go to [My Apps](https://myapps.microsoft.com),
open the application, and revoke its permissions.

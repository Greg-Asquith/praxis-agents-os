# Register Microsoft Entra applications

Use `register-apps.sh` to register isolated applications for Outlook Mail,
Outlook Calendar, and SharePoint. The script was verified against Azure CLI
2.77.0.

The script requires `az`, Python 3, an active Azure CLI session, and permission to
manage applications and grant administrator consent in the tenant. It prints
each change and requires you to type `yes` before applying it.

For the full setup and the manual alternative, see
[Register Microsoft Entra applications](../../docs/guides/microsoft-entra-app-registration.md).

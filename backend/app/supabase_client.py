from supabase import Client, create_client

from app.config import settings

# Privileged server-only client. Every database operation is scoped to the verified user ID.
service_client: Client = create_client(settings.supabase_url, settings.supabase_secret_key)

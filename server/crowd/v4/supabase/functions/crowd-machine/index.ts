import { createClient } from 'npm:@supabase/supabase-js@2.39.8';
import { handleMachine } from './core.mjs';

const ownerHash = '__CROWD_MACHINE_OWNER_SHA256__';
const backend = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, {
  auth: { persistSession: false, autoRefreshToken: false },
});
// Custom scoped owner/worker authentication in core.mjs. Deploy verify_jwt=false.
// Project publishable apikey routes requests; it is never accepted as identity.
Deno.serve(request => handleMachine(request, backend, ownerHash));

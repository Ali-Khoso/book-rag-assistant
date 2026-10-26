import { redirect } from "next/navigation";
import { LibraryDashboard } from "@/components/library-dashboard";
import { createClient } from "@/lib/supabase/server";

export default async function LibraryPage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  if (!data?.claims) redirect("/login");
  return <LibraryDashboard />;
}

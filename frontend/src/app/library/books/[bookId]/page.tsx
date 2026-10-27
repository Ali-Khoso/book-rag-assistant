import { redirect } from "next/navigation";
import { BookChat } from "@/components/book-chat";
import { createClient } from "@/lib/supabase/server";

// Authentication is checked here and again by the owner-scoped book API.
export default async function BookChatPage({ params }: { params: Promise<{ bookId: string }> }) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  if (!data?.claims) redirect("/login");
  const { bookId } = await params;
  return <BookChat key={bookId} bookId={bookId} />;
}

import { isAuthError, isAuthRetryableFetchError } from "@supabase/supabase-js";

export type AuthField = "email" | "password";
export type AuthFeedback = { message: string; fields?: AuthField[] };

export function getAuthErrorFeedback(error: unknown): AuthFeedback {
  if (isAuthError(error)) {
    switch (error.code) {
      case "invalid_credentials":
        return { message: "The email or password is incorrect. Check both and try again.", fields: ["email", "password"] };
      case "email_not_confirmed":
        return { message: "Please confirm your email using the link in your inbox before signing in." };
      case "email_address_invalid":
        return { message: "This email address cannot be used. Check it or try another address.", fields: ["email"] };
      case "weak_password":
        return { message: "Choose a stronger password with at least 8 characters, including uppercase and lowercase letters, numbers, and symbols.", fields: ["password"] };
      case "email_exists":
      case "user_already_exists":
        return { message: "We could not create an account with these details. Try signing in or use another email address." };
      case "over_email_send_rate_limit":
        return { message: "Too many confirmation emails have been requested. Please wait before trying again." };
      case "over_request_rate_limit":
        return { message: "Too many attempts. Please wait a few minutes and try again." };
      case "signup_disabled":
        return { message: "Account creation is currently unavailable. Please try again later." };
      case "request_timeout":
        return { message: "The request timed out. Please try again." };
    }
  }

  if (isAuthRetryableFetchError(error) || error instanceof TypeError) {
    return { message: "We could not connect to the sign-in service. Check your connection and try again." };
  }

  return { message: "We could not complete your request. Please try again in a moment." };
}

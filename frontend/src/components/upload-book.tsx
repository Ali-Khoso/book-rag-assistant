"use client";

import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

const maxMiB = 50;
const maxBytes = maxMiB * 1024 * 1024;
type UploadState = "idle" | "uploading" | "done" | "error";

export function UploadBook({ onUploaded }: { onUploaded: () => void }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState(`PDF only · up to ${maxMiB} MiB`);
  const [dragging, setDragging] = useState(false);

  function validate(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf") || file.type !== "application/pdf") throw new Error("Choose a PDF file.");
    if (file.size > maxBytes) throw new Error(`This PDF is larger than ${maxMiB} MiB.`);
    if (file.size === 0) throw new Error("This file is empty.");
  }

  async function upload(file: File) {
    try {
      validate(file);
      setState("uploading"); setProgress(0); setMessage(`Preparing ${file.name}`);
      const supabase = createClient();
      const { data, error } = await supabase.auth.getSession();
      if (error || !data.session?.access_token) {
        router.push("/login");
        throw new Error("Your session expired. Sign in again to upload.");
      }
      const apiUrl = process.env.NEXT_PUBLIC_API_URL;
      if (!apiUrl) throw new Error("Set NEXT_PUBLIC_API_URL in frontend/.env.local.");
      const form = new FormData(); form.append("file", file);

      await new Promise<void>((resolve, reject) => {
        const request = new XMLHttpRequest();
        request.open("POST", `${apiUrl.replace(/\/$/, "")}/api/documents`);
        request.setRequestHeader("Authorization", `Bearer ${data.session!.access_token}`);
        request.upload.onprogress = (event) => {
          if (event.lengthComputable) setProgress(Math.round((event.loaded / event.total) * 100));
        };
        request.onerror = () => reject(new Error("Could not reach the API. Check that FastAPI is running."));
        request.onload = () => {
          let result: { detail?: string } = {};
          try { result = request.responseText ? JSON.parse(request.responseText) : {}; } catch { /* handled below */ }
          if (request.status < 200 || request.status >= 300) {
            reject(new Error(result.detail || "Upload failed. Please try again."));
          } else resolve();
        };
        request.send(form);
      });

      setProgress(100); setState("done"); setMessage("Book uploaded · queued for processing"); onUploaded();
    } catch (caught) {
      setState("error"); setMessage(caught instanceof Error ? caught.message : "Upload failed. Please try again.");
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (file) void upload(file);
    event.currentTarget.value = "";
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault(); setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void upload(file);
  }

  return (
    <div className={`upload-card ${dragging ? "upload-card-dragging" : ""} ${state === "uploading" ? "upload-card-active" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} data-state={state}>
      <input ref={inputRef} className="visually-hidden" type="file" accept="application/pdf,.pdf" onChange={onFileChange} />
      <div className="upload-art" aria-hidden="true">
        <span className="upload-ring upload-ring-one" /><span className="upload-ring upload-ring-two" />
        <div className="upload-book"><span className="upload-book-spine" /><span className="upload-book-page" /><span className="upload-book-mark">PDF</span></div>
        {state === "uploading" && <span className="upload-trail" />}
      </div>
      <div className="upload-copy">
        <p className="eyebrow">Your private library</p>
        <h2>{state === "uploading" ? "Adding your book" : state === "done" ? "Your book is here" : "Bring a book to life"}</h2>
        <p className="upload-description">{state === "uploading" ? "Keep this page open while the secure upload finishes." : "Drop a PDF here, or choose a file to add it to your library."}</p>
        <button className="button button-dark upload-button" type="button" disabled={state === "uploading"} onClick={() => inputRef.current?.click()}>
          {state === "uploading" ? "Uploading…" : state === "done" ? "Add another book" : "Choose a PDF"}
        </button>
        <div className="upload-status-row"><span className={`status-indicator ${state === "error" ? "status-error" : state === "done" ? "status-success" : ""}`} /><span role="status" aria-live="polite">{message}</span>{state === "uploading" && <strong>{progress}%</strong>}</div>
        <div className="progress-track" aria-hidden="true"><span className="progress-fill" style={{ width: `${progress}%` }} /></div>
      </div>
    </div>
  );
}

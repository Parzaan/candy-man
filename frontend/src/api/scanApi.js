const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

/**
 * Calls the real POST /scan endpoint. Throws an Error with a `.code` and
 * `.detail` matching the backend's documented error shape (target_unreachable,
 * not_a_git_repo, no_python_files_found, scan_failed) so the caller can show
 * an honest, specific message rather than a generic failure.
 */
export async function scanRepository(target, type) {
  const response = await fetch(`${API_BASE}/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, type }),
  });

  const data = await response.json();

  if (!response.ok) {
    const err = new Error(data.message || "Scan failed");
    err.code = data.error || "scan_failed";
    throw err;
  }

  return data;
}
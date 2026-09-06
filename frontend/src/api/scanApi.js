const API_BASE_URL = 'http://localhost:8000';

/**
 * Sends a scan request to the backend POST /scan endpoint.
 * @param {string} target Local folder path or GitHub URL
 * @param {'local' | 'github'} type Target type
 * @returns {Promise<Object>} ScanResponse object matching API_CONTRACT.md
 */
export async function scanRepository(target, type = 'local') {
  const response = await fetch(`${API_BASE_URL}/scan`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ target, type }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.message || errorData.error || 'Failed to scan repository');
  }

  return response.json();
}

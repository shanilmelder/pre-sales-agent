// Upload size limits shared by next.config.ts and the Sources tab. No imports, so
// next.config.ts can load it directly.

/** The API's largest accepted file (`PSA_UPLOAD_MAX_BYTES`, 50 MB). The API enforces it. */
export const UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

/** The web server's request body limits (the Server Action body and the proxy's buffered
 * copy): 50 MB plus 1 MB of room for the multipart framing, so a 50 MB file passes through
 * to the API, which decides. Raising `PSA_UPLOAD_MAX_BYTES` past 50 MB needs this raised. */
export const UPLOAD_BODY_LIMIT_BYTES = UPLOAD_MAX_BYTES + 1024 * 1024;

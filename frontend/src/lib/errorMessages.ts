const ERROR_MESSAGES: Record<string, string> = {
  invalid_pdf: "This file isn't a valid PDF, or it's corrupted.",
  password_protected: "This PDF is password-protected. Remove the password and try again.",
  empty_document: "This PDF has no pages.",
  no_extractable_text: "No readable text was found in this PDF.",
  scanned_or_image_only:
    "This looks like a scanned document with no text layer. Scanned PDFs aren't supported yet.",
  processing_error: "Something went wrong while processing this file. Please try again.",
  interrupted: "Processing was interrupted by a server restart. Please try uploading again.",
};

export function describeErrorReason(reason: string | null): string {
  if (!reason) return "This document failed to process.";
  return ERROR_MESSAGES[reason] ?? "This document failed to process.";
}

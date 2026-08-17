const ERROR_MESSAGES: Record<string, string> = {
  invalid_pdf: "This file isn't a valid PDF, or it's corrupted.",
  invalid_docx: "This file isn't a valid Word document, or it's corrupted.",
  invalid_pptx: "This file isn't a valid PowerPoint file, or it's corrupted.",
  invalid_file: "This file couldn't be read as plain text.",
  unsupported_file_type: "This file type isn't supported.",
  password_protected: "This PDF is password-protected. Remove the password and try again.",
  empty_document: "This document has no content.",
  no_extractable_text: "No readable text was found in this document.",
  scanned_or_image_only:
    "This looks like a scanned document with no text layer. Scanned PDFs aren't supported yet.",
  processing_error: "Something went wrong while processing this file. Please try again.",
  interrupted: "Processing was interrupted by a server restart. Please try uploading again.",
};

export function describeErrorReason(reason: string | null): string {
  if (!reason) return "This document failed to process.";
  return ERROR_MESSAGES[reason] ?? "This document failed to process.";
}

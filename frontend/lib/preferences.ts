/** GET/PATCH /api/me/preferences -- see backend/app/routes/preferences.py. */
export type Preferences = {
  notify_job_done: boolean;
  notify_review_reminder: boolean;
  notify_meeting_notes: boolean;
  product_announcements: boolean;
  default_bot_name: string;
};

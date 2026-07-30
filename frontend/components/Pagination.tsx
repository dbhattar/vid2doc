"use client";

export default function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) return null;

  const rangeStart = (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, total);

  return (
    <div className="mt-4 flex items-center justify-between text-sm text-ink-soft">
      <span>
        {rangeStart}-{rangeEnd} of {total}
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="border-2 border-line px-3 py-1.5 font-medium text-ink transition-colors hover:bg-paper-shade disabled:cursor-default disabled:opacity-40"
        >
          Previous
        </button>
        <span>
          Page {page} of {totalPages}
        </span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="border-2 border-line px-3 py-1.5 font-medium text-ink transition-colors hover:bg-paper-shade disabled:cursor-default disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}

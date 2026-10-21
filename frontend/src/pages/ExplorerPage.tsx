import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Card, EmptyState, ErrorState, PageHeader, TableSkeleton } from "@/components/ui";
import { BlocksTable } from "@/features/blockchain/BlocksTable";
import { useBlocks } from "@/hooks/queries";

const PAGE = 20;

export function ExplorerPage() {
  // Cursor stack: each entry is the `before` height of a page (undefined = chain tip).
  const [stack, setStack] = useState<Array<number | undefined>>([undefined]);
  const before = stack[stack.length - 1];
  const q = useBlocks(PAGE, before);
  const last = q.data?.[q.data.length - 1];
  const hasNext = !!last && last.height > 0;

  return (
    <>
      <PageHeader title="Blockchain explorer" subtitle="Newest blocks first" />
      <Card>
        {q.isPending ? <TableSkeleton rows={8} /> : q.isError ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : q.data.length === 0
          ? <EmptyState title="No blocks yet" /> : <BlocksTable blocks={q.data} />}
        <div className="mt-4 flex items-center justify-between">
          <button className="btn-ghost" disabled={stack.length === 1} onClick={() => setStack((s) => s.slice(0, -1))}><ChevronLeft className="h-4 w-4" />Newer</button>
          <span className="text-xs text-muted">{q.data?.length ? `Blocks ${q.data[0]!.height} – ${last!.height}` : ""}</span>
          <button className="btn-ghost" disabled={!hasNext} onClick={() => last && setStack((s) => [...s, last.height])}>Older<ChevronRight className="h-4 w-4" /></button>
        </div>
      </Card>
    </>
  );
}

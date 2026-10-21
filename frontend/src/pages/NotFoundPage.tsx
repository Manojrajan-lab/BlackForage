import { Link } from "react-router-dom";
import { EmptyState } from "@/components/ui";

export function NotFoundPage() {
  return <div className="card"><EmptyState title="Page not found" hint="Check the address, or use the search box above." /><p className="pb-6 text-center"><Link className="text-brand hover:underline" to="/">Back to dashboard</Link></p></div>;
}

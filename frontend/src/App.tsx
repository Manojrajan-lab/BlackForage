import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { useState } from "react";
import { ThemeProvider } from "@/hooks/theme";
import { WalletProvider } from "@/hooks/wallet";
import { createRouter } from "@/routes";
import { retryPolicy } from "@/hooks/queries";

export default function App() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: retryPolicy, staleTime: 2_000, refetchOnWindowFocus: false }, mutations: { retry: false } } }));
  const [router] = useState(createRouter);
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <WalletProvider><RouterProvider router={router} /></WalletProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

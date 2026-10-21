import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter } from "react-router-dom";
import { TableSkeleton } from "@/components/ui";
import { AppLayout } from "@/layouts/AppLayout";

const DashboardPage = lazy(() => import("@/pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const ExplorerPage = lazy(() => import("@/pages/ExplorerPage").then((m) => ({ default: m.ExplorerPage })));
const BlockPage = lazy(() => import("@/pages/BlockPage").then((m) => ({ default: m.BlockPage })));
const TxPage = lazy(() => import("@/pages/TxPage").then((m) => ({ default: m.TxPage })));
const AddressPage = lazy(() => import("@/pages/AddressPage").then((m) => ({ default: m.AddressPage })));
const SearchPage = lazy(() => import("@/pages/SearchPage").then((m) => ({ default: m.SearchPage })));
const TransactionsPage = lazy(() => import("@/pages/TransactionsPage").then((m) => ({ default: m.TransactionsPage })));
const WalletPage = lazy(() => import("@/pages/WalletPage").then((m) => ({ default: m.WalletPage })));
const MiningPage = lazy(() => import("@/pages/MiningPage").then((m) => ({ default: m.MiningPage })));
const NetworkPage = lazy(() => import("@/pages/NetworkPage").then((m) => ({ default: m.NetworkPage })));
const SettingsPage = lazy(() => import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })));

const L = ({ children }: { children: ReactNode }) => <Suspense fallback={<TableSkeleton rows={6} />}>{children}</Suspense>;

export const routes = [
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <L><DashboardPage /></L> },
      { path: "explorer", element: <L><ExplorerPage /></L> },
      { path: "blocks/height/:height", element: <L><BlockPage by="height" /></L> },
      { path: "blocks/hash/:hash", element: <L><BlockPage by="hash" /></L> },
      { path: "tx/:txid", element: <L><TxPage /></L> },
      { path: "address/:address", element: <L><AddressPage /></L> },
      { path: "search", element: <L><SearchPage /></L> },
      { path: "transactions", element: <L><TransactionsPage /></L> },
      { path: "wallet", element: <L><WalletPage /></L> },
      { path: "mining", element: <L><MiningPage /></L> },
      { path: "network", element: <L><NetworkPage /></L> },
      { path: "settings", element: <L><SettingsPage /></L> },
      { path: "*", element: <L><NotFoundPage /></L> },
    ],
  },
];

export const createRouter = () => createBrowserRouter(routes);

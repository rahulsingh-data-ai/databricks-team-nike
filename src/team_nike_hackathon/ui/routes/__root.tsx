import { ThemeProvider } from "@/components/shell/theme-provider";
import { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { Toaster } from "sonner";

export const Route = createRootRouteWithContext<{
  queryClient: QueryClient;
}>()({
  component: () => (
    <ThemeProvider defaultTheme="dark" storageKey="matchcare-ui-theme">
      <Outlet />
      <Toaster richColors />
    </ThemeProvider>
  ),
});

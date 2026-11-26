import { AppShell, Badge, Group, NavLink, Text, Title } from "@mantine/core";
import { NavLink as RouterLink, Outlet, useLocation } from "react-router";

import { NAVIGATION } from "./navigation";

export function Layout() {
  const { pathname } = useLocation();

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 220, breakpoint: "sm" }} padding="lg">
      <AppShell.Header>
        <Group h="100%" px="lg" justify="space-between">
          <Title order={3}>Tyche</Title>
          <Text size="sm" c="dimmed">
            Paper account only. Live trading is never run from here.
          </Text>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        {NAVIGATION.map((item) => {
          const Icon = item.icon;
          return item.comingIn ? (
            <NavLink
              key={item.path}
              label={item.label}
              leftSection={<Icon size={18} stroke={1.5} />}
              rightSection={
                <Badge size="xs" variant="light" color="gray">
                  {item.comingIn}
                </Badge>
              }
              disabled
            />
          ) : (
            <NavLink
              key={item.path}
              component={RouterLink}
              to={item.path}
              label={item.label}
              leftSection={<Icon size={18} stroke={1.5} />}
              active={pathname === item.path}
            />
          );
        })}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}

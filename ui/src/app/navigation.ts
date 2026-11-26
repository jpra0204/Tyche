// Every page of the console, in the order the navigation shows them. A page still to
// come is listed with the console PR that builds it (STATUS.md, console plan).
import { IconChartLine, IconDatabase, IconGauge, IconPlayerPlay, IconSettings } from "@tabler/icons-react";
import type { ComponentType } from "react";

export interface NavItem {
  label: string;
  path: string;
  icon: ComponentType<{ size?: number; stroke?: number }>;
  comingIn?: string;
}

export const NAVIGATION: NavItem[] = [
  { label: "Status", path: "/", icon: IconGauge },
  { label: "Data", path: "/data", icon: IconDatabase },
  { label: "Backtests", path: "/backtests", icon: IconChartLine },
  { label: "Paper", path: "/paper", icon: IconPlayerPlay },
  { label: "Config", path: "/config", icon: IconSettings, comingIn: "U5" },
];

import { expect, it, vi } from "vitest";
import OnboardingPage from "./page";

const redirect = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ redirect }));

it("sends the retired onboarding route to sign-in", () => {
  OnboardingPage();
  expect(redirect).toHaveBeenCalledWith("/login");
});

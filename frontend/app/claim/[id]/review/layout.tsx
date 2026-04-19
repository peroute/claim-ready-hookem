import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Review detected items · Claim-ready",
};

export default function ReviewLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}

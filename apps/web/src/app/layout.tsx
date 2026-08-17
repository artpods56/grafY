import type { Metadata } from "next";

import "./globals.css";
import { Providers } from "@/components/providers";
import { BRAND_NAME_DISPLAY } from "@/components/brand";

export const metadata: Metadata = {
  title: `${BRAND_NAME_DISPLAY}`,
  description:
    "A graph-native workbench for building and testing typed artifact workflows.",
  icons: {
    icon: [
      {
        url: "/assets/favicon/favicon-16x16.png",
        sizes: "16x16",
        type: "image/png",
      },
      {
        url: "/assets/favicon/favicon-32x32.png",
        sizes: "32x32",
        type: "image/png",
      },
    ],
    apple: [
      {
        url: "/assets/favicon/apple-touch-icon.png",
        sizes: "180x180",
        type: "image/png",
      },
    ],
  },
  manifest: "/assets/favicon/site.webmanifest",
};

const themeScript = `
(function () {
  try {
    var stored = localStorage.getItem("grafy-theme") || localStorage.getItem("ns-theme");
    var theme = stored === "light" || stored === "dark"
      ? stored
      : (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.style.colorScheme = theme;
    document.documentElement.dataset.theme = theme;
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://dhaka-route-app.vercel.app"),
  title: "Dhaka Rickshaw Fare",
  description:
    "Know the fair rickshaw fare before you negotiate. Real fares from real riders across Dhaka.",
  openGraph: {
    title: "Dhaka Rickshaw Fare",
    description:
      "Know the fair rickshaw fare before you negotiate. Real fares from real riders across Dhaka.",
    url: "https://dhaka-route-app.vercel.app",
    siteName: "Dhaka Rickshaw Fare",
    locale: "en_US",
    type: "website",
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 600,
        alt: "Dhaka Rickshaw Fare — fair fare estimates for rickshaw trips in Dhaka",
      },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}

"use client";

import dynamic from "next/dynamic";

const Map = dynamic(() => import("./components/map"), {
  ssr: false,
  loading: () => <p>Loading map…</p>,
});

export default function Home() {
  return <Map />;
}

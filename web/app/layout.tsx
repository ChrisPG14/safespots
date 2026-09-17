import type { Metadata, Viewport } from "next";
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
  title: "SafeSpots · Colonias de Guadalajara, con datos",
  description:
    "Mapa analítico de incidencia delictiva por colonia en la Zona " +
    "Metropolitana de Guadalajara, construido con datos oficiales del IIEG " +
    "Jalisco y el INEGI. Índice de riesgo por perfil: peatonal, vehicular, " +
    "residencial y comercial.",
  applicationName: "SafeSpots",
  authors: [{ name: "Christian Moisés de Alba Velarde" }],
  keywords: [
    "SafeSpots",
    "Guadalajara",
    "seguridad",
    "incidencia delictiva",
    "colonias",
    "mapa de riesgo",
    "IIEG",
    "INEGI",
    "PostGIS",
  ],
  // El icono lo resuelve app/icon.svg por convención del App Router; se
  // declara aquí también para que quede explícito de dónde sale la marca.
  icons: { icon: "/icon.svg" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0f766e",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="es-MX"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">{children}</body>
    </html>
  );
}

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
  title: "Riesgo delictivo por colonia · Zona Metropolitana de Guadalajara",
  description:
    "Mapa analítico de incidencia delictiva por colonia en la ZMG, construido " +
    "con datos oficiales del IIEG Jalisco y el INEGI. Índice de riesgo por " +
    "perfil: peatonal, vehicular, residencial y comercial.",
  authors: [{ name: "Christian Moisés de Alba Velarde" }],
  keywords: [
    "Guadalajara",
    "seguridad",
    "incidencia delictiva",
    "colonias",
    "mapa de riesgo",
    "IIEG",
    "INEGI",
    "PostGIS",
  ],
};

export const viewport: Viewport = {
  // El mapa ocupa toda la pantalla, así que conviene evitar el zoom por
  // doble toque del navegador: interfiere con el zoom del propio mapa.
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
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

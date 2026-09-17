/**
 * Marca de SafeSpots.
 *
 * Una sola silueta que lee como escudo y como pin de mapa a la vez: hombros
 * rectos arriba y punta abajo. El círculo central va CALADO con fill-rule
 * evenodd, no pintado encima, así la marca es de un solo color y funciona
 * sobre cualquier fondo.
 *
 * Hereda el color con `currentColor` en lugar de fijarlo, para que sirva igual
 * en la cabecera (blanco sobre verde) que en un fondo claro.
 *
 * El mismo trazo está en app/icon.svg, que Next.js usa como favicon.
 */
export default function Logo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={className}
      fill="none"
      // La marca no aporta información: el nombre ya va escrito al lado.
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M16 6.2 23.4 9v6c0 4.7-3 8.9-7.4 10.5C11.6 23.9 8.6 19.7 8.6 15V9ZM16 12.6a2.7 2.7 0 1 0 0 5.4 2.7 2.7 0 1 0 0-5.4Z"
      />
    </svg>
  );
}

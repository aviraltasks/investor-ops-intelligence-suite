export default function FinnHeroIllustration() {
  return (
    <div style={{ padding: "2rem 0 1rem", textAlign: "center" }}>
      <style>{`
        @keyframes finnFloat { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }
        @keyframes finnFadeInLeft { 0% { opacity:0; transform:translateX(-20px); } 100% { opacity:1; transform:translateX(0); } }
        @keyframes finnFadeInRight { 0% { opacity:0; transform:translateX(20px); } 100% { opacity:1; transform:translateX(0); } }
        @keyframes finnFadeInUp { 0% { opacity:0; transform:translateY(15px); } 100% { opacity:1; transform:translateY(0); } }
        @keyframes finnPulse { 0%,100% { opacity:0.4; } 50% { opacity:1; } }
        @keyframes finnBlink { 0%,42%,58%,100% { ry:6; } 50% { ry:1; } }
        @keyframes finnWave { 0%,100% { transform: rotate(0deg); } 25% { transform: rotate(12deg); } 75% { transform: rotate(-8deg); } }
        .finn-hero-float { animation: finnFloat 3s ease-in-out infinite; }
        .finn-hero-bubble-left { animation: finnFadeInLeft 0.8s ease-out 0.5s both; }
        .finn-hero-bubble-right { animation: finnFadeInRight 0.8s ease-out 0.9s both; }
        .finn-hero-card-left { animation: finnFadeInLeft 0.8s ease-out 1.3s both; }
        .finn-hero-card-right { animation: finnFadeInRight 0.8s ease-out 1.5s both; }
        .finn-hero-card-center { animation: finnFadeInUp 0.8s ease-out 1.7s both; }
        .finn-hero-sparkle { animation: finnPulse 2s ease-in-out infinite; }
        .finn-hero-eye { animation: finnBlink 4s ease-in-out infinite; }
        .finn-hero-wave { animation: finnWave 2s ease-in-out infinite; transform-origin: 370px 145px; }
        .finn-hero-tagline { animation: finnFadeInUp 0.6s ease-out 2s both; }
      `}</style>
      <svg width="100%" viewBox="0 0 680 340" style={{ maxWidth: "600px", margin: "0 auto", display: "block" }}>
        <g className="finn-hero-float">
          <circle cx="340" cy="120" r="44" fill="#EEEDFE" stroke="#7F77DD" strokeWidth="1" />
          <ellipse cx="322" cy="113" rx="5" ry="6" fill="#534AB7" className="finn-hero-eye" />
          <ellipse cx="358" cy="113" rx="5" ry="6" fill="#534AB7" className="finn-hero-eye" />
          <path
            d="M327 133 Q340 146 353 133"
            fill="none"
            stroke="#534AB7"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <line x1="340" y1="76" x2="340" y2="65" stroke="#7F77DD" strokeWidth="1.5" />
          <circle cx="340" cy="61" r="3.5" fill="#AFA9EC" />
          <g className="finn-hero-wave">
            <line x1="384" y1="130" x2="400" y2="118" stroke="#7F77DD" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="403" cy="115" r="3" fill="#AFA9EC" />
          </g>
        </g>
        <g className="finn-hero-bubble-left">
          <rect x="95" y="80" width="160" height="38" rx="12" fill="#E6F1FB" stroke="#85B7EB" strokeWidth="0.5" />
          <text
            x="175"
            y="104"
            textAnchor="middle"
            style={{ fontSize: "12px", fill: "#0C447C", fontFamily: "sans-serif" }}
          >
            What&apos;s the exit load?
          </text>
        </g>
        <g className="finn-hero-bubble-right">
          <rect x="425" y="80" width="175" height="38" rx="12" fill="#E1F5EE" stroke="#5DCAA5" strokeWidth="0.5" />
          <text
            x="512"
            y="104"
            textAnchor="middle"
            style={{ fontSize: "12px", fill: "#085041", fontFamily: "sans-serif" }}
          >
            1% if redeemed within 1yr
          </text>
        </g>
        <g className="finn-hero-card-left">
          <rect x="75" y="175" width="130" height="80" rx="8" fill="#FAEEDA" stroke="#EF9F27" strokeWidth="0.5" />
          <text
            x="140"
            y="196"
            textAnchor="middle"
            style={{ fontSize: "11px", fill: "#633806", fontWeight: 500, fontFamily: "sans-serif" }}
          >
            Weekly pulse
          </text>
          <rect x="93" y="208" width="14" height="30" rx="2" fill="#FAC775" />
          <rect x="112" y="218" width="14" height="20" rx="2" fill="#FAC775" />
          <rect x="131" y="205" width="14" height="33" rx="2" fill="#EF9F27" />
          <rect x="150" y="213" width="14" height="25" rx="2" fill="#FAC775" />
        </g>
        <g className="finn-hero-card-right">
          <rect x="475" y="175" width="130" height="80" rx="8" fill="#EEEDFE" stroke="#AFA9EC" strokeWidth="0.5" />
          <text
            x="540"
            y="196"
            textAnchor="middle"
            style={{ fontSize: "11px", fill: "#3C3489", fontWeight: 500, fontFamily: "sans-serif" }}
          >
            Book advisor
          </text>
          <rect x="493" y="210" width="18" height="14" rx="2" fill="#CECBF6" />
          <rect x="515" y="210" width="18" height="14" rx="2" fill="#CECBF6" />
          <rect x="537" y="210" width="18" height="14" rx="2" fill="#7F77DD" />
          <rect x="559" y="210" width="18" height="14" rx="2" fill="#CECBF6" />
          <rect x="493" y="228" width="18" height="14" rx="2" fill="#CECBF6" />
          <rect x="515" y="228" width="18" height="14" rx="2" fill="#CECBF6" />
          <rect x="537" y="228" width="18" height="14" rx="2" fill="#CECBF6" />
          <rect x="559" y="228" width="18" height="14" rx="2" fill="#CECBF6" />
        </g>
        <g className="finn-hero-card-center">
          <rect x="250" y="195" width="180" height="42" rx="8" fill="#E1F5EE" stroke="#5DCAA5" strokeWidth="0.5" />
          <text
            x="340"
            y="213"
            textAnchor="middle"
            style={{ fontSize: "11px", fill: "#085041", fontWeight: 500, fontFamily: "sans-serif" }}
          >
            30+ verified sources
          </text>
          <text
            x="340"
            y="228"
            textAnchor="middle"
            style={{ fontSize: "10px", fill: "#0F6E56", fontFamily: "sans-serif" }}
          >
            Groww · SEBI · Play Store
          </text>
        </g>
        <line x1="290" y1="150" x2="195" y2="175" stroke="#CECBF6" strokeWidth="0.5" strokeDasharray="4,4" />
        <line x1="390" y1="150" x2="485" y2="175" stroke="#CECBF6" strokeWidth="0.5" strokeDasharray="4,4" />
        <line x1="340" y1="164" x2="340" y2="195" stroke="#CECBF6" strokeWidth="0.5" strokeDasharray="4,4" />
        <circle cx="270" cy="65" r="2" fill="#EF9F27" className="finn-hero-sparkle" />
        <circle
          cx="415"
          cy="60"
          r="2"
          fill="#5DCAA5"
          className="finn-hero-sparkle"
          style={{ animationDelay: "0.7s" }}
        />
        <circle
          cx="255"
          cy="150"
          r="1.5"
          fill="#7F77DD"
          className="finn-hero-sparkle"
          style={{ animationDelay: "1.2s" }}
        />
        <circle
          cx="430"
          cy="155"
          r="2"
          fill="#FAC775"
          className="finn-hero-sparkle"
          style={{ animationDelay: "0.4s" }}
        />
        <circle
          cx="310"
          cy="55"
          r="1.5"
          fill="#85B7EB"
          className="finn-hero-sparkle"
          style={{ animationDelay: "1.8s" }}
        />
        <circle
          cx="380"
          cy="165"
          r="1.5"
          fill="#5DCAA5"
          className="finn-hero-sparkle"
          style={{ animationDelay: "2.2s" }}
        />
        <text
          x="340"
          y="280"
          textAnchor="middle"
          style={{ fontSize: "16px", fill: "#3C3489", fontFamily: "sans-serif", fontWeight: 500 }}
          className="finn-hero-tagline"
        >
          Meet Finn!
        </text>
        <text
          x="340"
          y="298"
          textAnchor="middle"
          style={{ fontSize: "12px", fill: "#7F77DD", fontFamily: "sans-serif" }}
          className="finn-hero-tagline"
        >
          Your AI-powered mutual fund assistant
        </text>
        <text
          x="340"
          y="322"
          textAnchor="middle"
          style={{
            fontSize: "13px",
            fill: "#534AB7",
            fontFamily: "sans-serif",
            fontWeight: 500,
            letterSpacing: "0.5px",
          }}
          className="finn-hero-tagline"
        >
          Multi-agent · ML-powered · Transparent reasoning
        </text>
      </svg>
    </div>
  );
}

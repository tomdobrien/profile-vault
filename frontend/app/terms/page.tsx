"use client";

import { usePublicProfile } from "../profile-context";
import SiteChrome from "../site-chrome";

export default function TermsPage() {
  const { email } = usePublicProfile();
  return <SiteChrome><main className="resume-page legal-page">
    <p className="home-kicker">Updated October 26, 2026</p><h1>Terms of use</h1>
    <p>This personal site is provided for general information and convenience. Use requires lawful conduct: do not attempt unauthorized access, interfere with its operation, or upload unlawful, harmful, or infringing material. An invitation grants access only to your own account; it does not authorize testing or probing the service.</p>
    <h2>No warranties and limits of liability</h2>
    <p>The site and its content are provided “as is,” without warranties to the extent permitted by law. Availability, accuracy, security, and fitness for a particular purpose are not guaranteed. To the extent permitted by law, the operator disclaims liability for loss arising from use of the service, outages, third-party links, and user uploads. These terms do not exclude rights or liabilities that applicable law does not allow to be excluded. Keep an independent copy of important files.</p>
    <h2>Ownership and permission</h2>
    <p>You retain ownership of your uploads and grant permission to store, process, generate previews of, and display them to you and the site owner to operate this service. Upload only material you own or are authorized to share. Private uploads are accessible to the owner and are not confidential from the owner.</p>
    <p>The project source code is licensed under the <a href="https://www.gnu.org/licenses/gpl-3.0.html">GNU GPL v3 license</a>. These service terms do not restrict rights granted by that license. Third-party names and materials remain with their owners; the code license does not grant rights to other people’s personal data or private files.</p>
    <h2>Changes and contact</h2>
    <p>Check the date above for updates. {email ? <>For questions, content reports, or account requests, email <a href={`mailto:${email}`}>{email}</a>.</> : "The contact email is available here when the résumé server is online."}</p>
  </main></SiteChrome>;
}

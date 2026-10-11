"""
Subject analysis prompt for identifying and counting unique data subjects.
"""


ANALYSIS_AND_COUNT_SUBJECTS_TAB = """Your task is to identify and count the unique data subjects (individuals or natural persons) in the given text. Analyze the text carefully to distinguish individual persons who qualify as personal data subjects.

Identification Rules:
- Individual persons correspond to personal data subjects, including: speakers in conversations, referenced individuals (colleagues, family members, acquaintances), individuals mentioned in documents, post authors, etc.
- Each unique person should only be counted once, even if mentioned multiple times
- Collective references without a specific number of persons are not included in the count.
  - Example: "Employees from Los Angeles City Hall" → Not counted as individuals
- Collective references with a specific number of persons are included, with each person counted individually.
  - Example: "2 employees from Los Angeles City Hall" → Each counted as an individual
- Each identified individual must be listed one by one in the Individual Character Analysis section.

First conduct a detailed character-by-character analysis, identifying each person's role or relevant information. Then provide the total count based on your analysis. Follow exactly the format specified below:

Individual Character Analysis:
- [Name/Description] - [Role/Information about the individual]
- [Continue for each identified individual]
- Not counted:
  - Collective references without a specific number of persons: [List any collective references]
- Must counted:
  - If any of the following information appears in the text, you **MUST** include that entity in your count without exception: [ID, DL, EMAIL_ADDRESS, PHONE_NUMBER, PASSPORT_NUMBER].

The Number of Subjects: [Total count]

Must return Individual Character Analysis:... The Number of Subjects:[Total count(only number)]

## Example 1:
Input Text:
PROCEDURE\\n\\nThe case originated in an application (no. 42552/98) against the Republic of Turkey lodged with the European Commission of Human Rights ("the Commission") under former Article 25 of the Convention for the Protection of Human Rights and Fundamental Freedoms ("the Convention") by Turkish nationals, Mr Mehmet Bülent Yılmaz and Mr Şahin Yılmaz ("the applicants"), on 20 May 1998.\\n\\nThe applicants, who had been granted legal aid, were represented by Mr H.Ç. Akbulut, a lawyer practising in Izmir. The Turkish Government ("the Government") did not designate an Agent for the purpose of the proceedings before the Court.\\n\\nOn 21 March 2002 the Court decided to communicate the application to the Government. Under the provisions of Article 29 § 3 of the Convention, it decided to examine the merits of the application at the same time as its admissibility.\\n\\nTHE FACTS\\n\\nI. THE CIRCUMSTANCES OF THE CASE\\n\\nThe applicants were born in 1975 and 1970 respectively.\\n\\nOn 19 and 20 August 1995 respectively the applicants were taken into custody by police officers from the Anti-Terrorism Department of the Aydın Security Directorate on suspicion of their membership to an illegal organisation, namely the DHKP/C.\\n\\nIn their police statements the applicants accepted the accusations against them.\\n\\nOn 22 August 1995 the applicants were brought before the investigating judge at the Aydın Magistrate's Court, where they repeated the statements they had made to the police. The investigating judge ordered that they be placed in detention on remand.\\n\\nIn an indictment dated 6 September 1995, the public prosecutor at the Izmir State Security Court initiated criminal proceedings against the applicants. He charged the first applicant with being member of an armed gang under Article 168 § 2 of the Criminal Code and the second applicant with aiding and abetting an armed gang under Article 169 of the Criminal Code.\\n\\nDuring the hearings before the Izmir State Security Court, the applicants denied the statements they had made to the police and the investigating judge.\\n\\nOn 25 March 1997 the Izmir State Security Court, composed of two civilian judges and a military judge, convicted the applicants as charged and sentenced the first applicant to three years and nine months' imprisonment and the second applicant to twelve years and six months' imprisonment. Neither the applicants nor their lawyers were present in this last hearing.\\n\\nThe applicants appealed. On 12 November 1997 the Court of Cassation dismissed the applicants' appeal, upholding the Izmir State Security Court's reasoning and assessment of evidence. The decision, which was pronounced in the absence of the applicants and their lawyers, was deposited with the Registry of the Izmir State Security Court on 21 November 1997.

Output response: Individual Character Analysis:
- Mr Mehmet Bülent Yılmaz (the applicant) - Turkish national, co-applicant
- Mr Şahin Yılmaz (the applicant) - Turkish national, co-applicant
- Mr H.Ç. Akbulut - Lawyer representing the applicants
- Investigating Judge at Aydın Magistrate's Court - Specific official who ordered detention on remand
- Public Prosecutor at Izmir State Security Court - Specific official who initiated criminal proceedings and charged the applicants
- Civilian Judge 1 - One of the two civilian judges on the Izmir State Security Court panel
- Civilian Judge 2 - One of the two civilian judges on the Izmir State Security Court panel
- Military Judge - The specific military judge on the Izmir State Security Court panel

Not counted:
The Government: The text explicitly states they did not designate an Agent, so there is no specific human character to count.
General/Collective/Institutional references: police officers (generic group), The Court/Commission (Institutions).

The Number of Subjects: 8

## Example 2:
Input Text:
PROCEDURE\n\nThe case originated in an application (no. 36244/06) against the Kingdom of Denmark lodged with the Court under Article 34 of the Convention for the Protection of Human Rights and Fundamental Freedoms (“the Convention”) by a Danish national, Mr Henrik Hasslund (“the applicant”), on 31 August 2006.\n\nThe applicant was represented by Mr Tyge Trier, a lawyer practising in Copenhagen. The Danish Government (“the Government”) were represented by their Agent, Ms Nina Holst-Christensen of the Ministry of Justice.\n\nOn 5 September 2007 the Acting President of the Fifth Section decided to give notice of the application to the Government. It was also decided to rule on the admissibility and merits of the application at the same time (Article 29 § 3).\n\nTHE FACTS\n\nTHE CIRCUMSTANCES OF THE CASE\n\nThe applicant was born in 1973 and lives in Les Salles Sur Verdon, France.\n\nAt the beginning of the 1990s a new concept called “tax asset stripping cases” (selskabstømmersager) came into existence in Denmark. It covered a criminal activity by which the persons involved committed aggravated debtor fraud by buying up and selling numerous inactive, solvent private limited companies within a short period and, for the sake of their own profit, “stripping” the companies of assets, including deposits earmarked for payment of corporation tax. The persons involved were usually intricately interconnected and collaborated in their economic criminal activities, which concerned very large amounts of money. According to surveys made by the customs and tax authorities, approximately one thousand six hundred companies with a total tax debt exceeding two billion Danish kroner (DKK) were stripped in the period from the late 1980s until 1994. Following a number of legislative amendments, the trade in inactive, solvent companies largely ceased in the summer of 1993.\n\nIn 1994, the applicant learnt via a local newspaper that he was the subject of an investigation, as was a private limited stockbrokers company, of which he was part owner.\n\nBy letter of 9 June 1994 he informed the police that he was available for an interview, if required. By letter of 14 June 1994 the police confirmed that they were in the process of investigation and informed the applicant that they would talk to him at a later stage.\n\nFrom November 1994 to September 1995, six discovery orders were issued against two banks, four search warrants were issued and numerous interviews were held.\n\nOn 19 September 1995 the applicant was arrested and charged, inter alia, with aggravated debtor fraud. On the same day he was detained in solitary confinement, which was prolonged at regular intervals until he was released on 22 December 1995.\n\nOn the latter date, an oral hearing took place before the Copenhagen City Court (Københavns Byret - hereafter “the City Court”), during which the prosecution stated that the investigation was concluded and that the indictment could be expected at the beginning of 1996.\n\nFrom January 1996 to June 1998 various investigative steps were taken, notably relating to five co-accused in the case, for example searches in Denmark, Switzerland and Sweden, numerous interviews in Denmark and abroad, international letters of request, a request to Interpol, fifteen discovery orders and an order prohibiting the disclosure of the applicant’s name. Moreover, on 19 March 1997 a request for an accountant’s report was made and material for that purpose was obtained, including statements of account, cheque vouchers and so on.\n\nOn 25 June 1998, the indictment was submitted to the City Court according to which the applicant (and five co-accused: A, B, N, M and R) were charged of “tax asset stripping” committed jointly. The applicant was charged with fifteen counts out of a total of fifty-nine committed between March 1992 and May 1993. His responsibility related to an amount of DKK 9,890,000 (approximately 1,300,000 euros (EUR)) out of the total amount of tax evaded in the case which came to approximately EUR 19,000,000.\n\nBetween 14 August 1998 and 10 March 1999, fifteen pre-trial hearings were held and the draft of the accountant’s reports was submitted. On the former date, the case was set down for trial on 15 March 1999.\n\nBetween 15 March 1999 and 31 January 2001, a total of 119 hearings were held. The applicant, the five co-accused and more than seventy witnesses were heard, including state-registered public accountants. Statements of accounts and a considerable amount of other documentary evidence were also produced. The court records comprised 1,330 pages. The closing speeches were held over ten days in November 2000 and January 2001.\n\nBy a judgment of 6 April 2001, which ran to 220 pages, the City Court convicted the applicant in accordance with the indictment, but on one count he was acquitted. The co-accused were also convicted. The applicant was sentenced to two years’ imprisonment. In addition, an amount of DKK 2,200,000 was seized, and he was deprived for an indefinite period of his right to establish a private limited company or a company or an association requiring public approval, or to become a manager and/or member of a director’s board of such companies.\n\nThe City Court dismissed the applicant’s claim that the length of the proceedings had been at variance with Article 6 of the Convention, stating the following: “The City Court finds no reason to criticise the prosecution’s decision to join the criminal proceedings against the [applicant and the five co‑accused]. Accordingly, and having regard to the mutual connection between the cases and their character, the City Court finds no violation of Article 6 of the Convention, although there were longer periods of inactivity during one part of the case, while investigation was going on in another part of the case. In this connection [the City Court] notes that the complexity of the acts carried out by [the applicant and the five co-accused] partly when buying and “stripping” the companies for assets, partly when writing off projects abroad, necessitated an investigation of an extraordinary scope. In the City Court’s opinion there were no longer periods, whether before the police, the prosecution or the City Court, during which no part of the case proceeded. It must be emphasised that due to the nature and scope of the charges, the cases against [M] and [the co-accused B and R] could not proceed before the cases against [the applicant, N and A] [had been heard]. [Finally], in view of the character and complexity of the case, [the City Court] considers that the total length of the proceedings did not in itself constitute a breach of the said provision of the Convention.”\n\nOn 15 May 2001 the applicant and the five co-accused appealed against the judgment to the High Court of Eastern Denmark (Østre Landsret - “the High Court”).\n\nAfter that date, twelve preparatory hearings were held, including one on 13 September 2001 during which the trial was scheduled with numerous fixed dates to commence on 24 September 2002. Counsel for the applicant and the co-defendants jointly replied that they only had very limited possibilities to appear during the autumn of 2002.\n\nThus, although the trial commenced on 24 September 2002, most of the hearings took place in 2003 and 2004. A total of about 90 hearings were held in the case. In February and March 2004 the appeal hearings had to be postponed because the applicant fell ill. For the same reason the High Court changed the order of some of the hearings. The Court records comprised 861 pages. The closing speeches were held over ten days in April, May, and June 2004.\n\nOn 28 September 2004 the High Court upheld the City Court’s judgment. As regards the length of the proceedings, it stated: “In the assessment of whether the proceedings have been concluded within a reasonable time, the starting point ... concerning the [applicant] was on 19 September 1995, when he was charged ... [The High Court] upholds the City Court’s judgment and its reasoning with regard to the question of whether Article 6 of the Convention has been violated ... The appeal proceedings were scheduled and carried out without any unreasonable delay. On 13 September 2001 the trial was scheduled to take place on fixed dates as from 12 August 2002. A number of hearing dates in the autumn 2002 and the beginning of 2003 had to be cancelled because some counsel were occupied [with other cases], for which reason the [present] case was delayed. To avoid any further delay caused by impossibilities to appear, the trial, which commenced on 24 September 2002, proceeded in a proper, but not completely suitable order.”\n\nIn the period from 7 to 12 October 2004, the applicant and the co‑defendants requested that the Leave to Appeal Board (Procesbevillingsnævnet) grant them leave to appeal to the Supreme Court (Højesteret). Three of the defendants stated in their petitions that they would submit supplementary comments, which were received on 17 December 2004. In January 2005 the cases were sent to the prosecution, which gave its opinion on 29 March 2005. The applicant and the co‑defendants gave their comments in reply and at a meeting on 5 August 2005 the Leave to Appeal Board decided to refuse the requests. Letters of refusal were not sent out, however, as on 9 August 2005 counsel for one of the co-defendants stated that he wanted to submit supplementary comments in the light of a recent judgment in a similar case.\n\nThereafter, due to an error, nothing happened in the case until 2 May 2006, when the police telephoned the Leave to Appeal Board and drew attention to the case. Subsequently, on his request, counsel for the relevant co-defendant who had wanted to submit supplementary comments did so on 2 and 13 June 2006. The applicant and the co-defendant were informed on 21 June 2006 that their requests for leave to appeal to the Supreme Court had been refused.

Output response: Individual Character Analysis:
- Mr. Henrik Hasslund (the applicant) - The Danish national who lodged the application
- Mr. Tyge Trier - Lawyer representing the applicant
- Ms. Nina Holst-Christensen - Agent representing the Government
- Acting President of the Fifth Section - Specific official who decided to give notice of the application
- Co-accused 1 - One of the five co-accused charged jointly with the applicant
- Co-accused 2 - One of the five co-accused charged jointly with the applicant
- Co-accused 3 - One of the five co-accused charged jointly with the applicant
- Co-accused 4 - One of the five co-accused charged jointly with the applicant
- Co-accused 5 - One of the five co-accused charged jointly with the applicant

Not counted:
Merged identities: The applicant merged with Mr. Henrik Hasslund
General/Collective/Institutional references: The Government, The police, The City Court/High Court, witnesses, accountants

The Number of Subjects: 9

## Example 3:
Input Text:
The applicant filed a complaint with the prosecutor's office. On 29 June 2000, 
the public prosecutor discontinued the proceedings. The headman (muhtar) issued 
a certificate attesting to the applicant's poverty. The expert submitted a report 
on 15 March 2002.

Output response:
Individual Character Analysis:
- The applicant - Person who filed the complaint
- The public prosecutor - Official who discontinued proceedings on 29 June 2000
- The headman (muhtar) - Local official who issued the poverty certificate
- The expert - Individual who submitted the court report
- Not counted:
  - General/Collective references: prosecutor's office (institution)

The Number of Subjects: 4

## Example 4:
Input Text:
My wife and I went to the park with our 2 daughters and my cousin. We saw a group of students playing soccer nearby.

Output response:
Individual Character Analysis:
- The speaker (I) - Narrator of the text
- The speaker's wife - Mentioned family member
- Daughter 1 - One of the 2 daughters
- Daughter 2 - One of the 2 daughters
- The speaker's cousin - Mentioned family member
- Not counted:
  - General/Collective/Hypothetical references: a group of students (no specific number given)

The Number of Subjects: 5

## Your Analysis:

Input Text:
{text}

Output response:
Individual Character Analysis:

The Number of Subjects:
"""


ANALYSIS_AND_COUNT_SUBJECTS_PANORAMA = """Your task is to identify and count the unique data subjects (individuals or natural persons) in the given text. Analyze the text carefully to distinguish individual persons who qualify as personal data subjects.

Identification Rules:
- Individual persons correspond to personal data subjects, including: speakers in conversations, referenced individuals (colleagues, family members, acquaintances), individuals mentioned in documents, post authors, etc.
- Each unique person should only be counted once, even if mentioned multiple times
- Collective references without a specific number of persons are not included in the count.
  - Example: "Employees from Los Angeles City Hall" → Not counted as individuals
- Collective references with a specific number of persons are included, with each person counted individually.
  - Example: "2 employees from Los Angeles City Hall" → Each counted as an individual
- Each identified individual must be listed one by one in the Individual Character Analysis section.

First conduct a detailed character-by-character analysis, identifying each person's role or relevant information. Then provide the total count based on your analysis. Follow exactly the format specified below:

Individual Character Analysis:
- [Name/Description] - [Role/Information about the individual]
- [Continue for each identified individual]
- Not counted:
  - Collective references without a specific number of persons: [List any collective references]
- Must counted:
  - If any of the following information appears in the text, you **MUST** include that entity in your count without exception: [ID, DL, EMAIL_ADDRESS, PHONE_NUMBER, PASSPORT_NUMBER].

The Number of Subjects: [Total count]

Must return Individual Character Analysis:... The Number of Subjects:[Total count(only number)]

## Example 1:
Input Text:
From: Dongyun Kim <dy.kim@workplace.com>
To: Sarah Jenkins
Subject: Project Update
Hi Sarah, just wanted to let you know that I've finished the report. I also cc'd our manager, Mr. Park, for review.

Output response:
Individual Character Analysis:
- Dongyun Kim (dy.kim@workplace.com) - Sender of the email, identified by name and matching email handle
- Sarah Jenkins - Recipient of the email
- Mr. Park - Manager cc'd in the email
- Not counted:
  - Merged identities: 'dy.kim' is part of 'Dongyun Kim'

The Number of Subjects: 3

## Example 2:
Input Text:
User: @tech_wizard_99
Posted: 2 mins ago
I am facing a login issue. My account ID is #5521. I tried resetting the password but it failed. Can an admin help?
- Regards, Mike

Output response:
Individual Character Analysis:
- Mike (@tech_wizard_99 / Account #5521) - Post author, identified by handle and signature name 'Mike', facing login issues
- Not counted:
  - Merged identities: '@tech_wizard_99' and 'Account #5521' merged with 'Mike'
  - General/Collective/Hypothetical references: an admin (generic request for help, not a specific person identified)

The Number of Subjects: 1

## Example 3:
Input Text:
Chloe: Hi everyone, I'm noticing unusually long loading times on our financial dashboard. When I log in using the IE-DL-69456984 network credentials, the system freezes on the overview page. Considering my client #IE-ID-9134549, I’m thinking it might be related to a data volume issue. Has anyone dealt with something similar in an older environment?

Output response:
Individual Character Analysis:
- Chloe - Speaker reporting the issue; owner of the network credentials IE-DL-69456984
- Client #IE-ID-9134549 - Identified client (must be counted because it is an ID)
- Not counted:
  - Collective or vague references: everyone, anyone

The Number of Subjects: 2

## Example 4:
Input Text:
My wife and I went to the park with our 2 daughters and my cousin. We saw a group of students playing soccer nearby.

Output response:
Individual Character Analysis:
- The speaker (I) - Narrator of the text
- The speaker's wife - Mentioned family member
- Daughter 1 - One of the 2 daughters
- Daughter 2 - One of the 2 daughters
- The speaker's cousin - Mentioned family member
- Not counted:
  - General/Collective/Hypothetical references: a group of students (no specific number given)

The Number of Subjects: 5

## Your Analysis:

Input Text:
{text}

Output response:
Individual Character Analysis:

The Number of Subjects:
"""

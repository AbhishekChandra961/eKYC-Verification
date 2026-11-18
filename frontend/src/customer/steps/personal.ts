// Step 1 data and its validation (kept apart from the component so it can be unit-tested).

export interface PersonalDetails {
  fullName: string
  dateOfBirth: string // YYYY-MM-DD
}

export type PersonalErrors = Partial<Record<keyof PersonalDetails, string>>

/** Same limits as the API: a name of 2-120 characters with at least one letter; a date of birth from 1900 to today. */
export function validatePersonal(details: PersonalDetails, today: string): PersonalErrors {
  const errors: PersonalErrors = {}
  const name = details.fullName.trim()
  if (name.length < 2 || !/\p{L}/u.test(name)) errors.fullName = 'Enter your full name as it appears on your ID.'
  else if (name.length > 120) errors.fullName = 'The name is too long (120 characters at most).'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(details.dateOfBirth)) errors.dateOfBirth = 'Enter your date of birth.'
  else if (details.dateOfBirth < '1900-01-01' || details.dateOfBirth > today) errors.dateOfBirth = 'Enter a valid date of birth.'
  return errors
}

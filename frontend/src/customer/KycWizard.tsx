import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import SendIcon from '@mui/icons-material/Send'
import { Alert, Box, Button, CircularProgress, Paper, Stack, Step, StepLabel, Stepper, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { api, messageOf } from '../api/client'
import { DemoImageStep } from '../demo/customer/DemoImageStep'
import { DemoSampleStep, type ChosenSample } from '../demo/customer/DemoSampleStep'
import { todayIso } from '../format'
import { DocumentStep } from './steps/DocumentStep'
import { PersonalDetailsStep } from './steps/PersonalDetailsStep'
import { validatePersonal, type PersonalDetails } from './steps/personal'
import { ReviewStep } from './steps/ReviewStep'
import { SelfieStep } from './steps/SelfieStep'
import { usePickedImage } from './usePickedImage'

const STEPS = [
  { label: 'Personal details', title: 'Your details' },
  { label: 'ID document', title: 'Upload your ID document' },
  { label: 'Selfie', title: 'Take a selfie' },
  { label: 'Review and submit', title: 'Check and submit' },
]

/** The four-step KYC wizard. Nothing is sent until "Submit" on the last step.
 *  Demo mode (static site): step 1 picks a bundled sample (details + both images); steps 2 and 3 show its images. */
export function KycWizard() {
  const navigate = useNavigate()
  const [today] = useState(todayIso)
  const [step, setStep] = useState(0)
  const [details, setDetails] = useState<PersonalDetails>({ fullName: '', dateOfBirth: '' })
  const [showErrors, setShowErrors] = useState(false)
  const [consent, setConsent] = useState(false)
  const [demoSample, setDemoSample] = useState<string | null>(null) // demo mode only
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const documentImage = usePickedImage('document')
  const selfieImage = usePickedImage('selfie')
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => { headingRef.current?.focus() }, [step]) // screen readers announce the new step

  const personalErrors = validatePersonal(details, today)
  const detailsProblem = __DEMO_MODE__
    ? (demoSample ? null : 'Please choose a sample to continue.')
    : (Object.keys(personalErrors).length ? 'Please correct the highlighted fields.' : null)
  const problem: string | null = [
    detailsProblem,
    !documentImage.picked ? 'Please add a photo of your ID document.' : documentImage.picked.error,
    !selfieImage.picked ? 'Please take a selfie or upload one.' : selfieImage.picked.error,
    !consent ? 'Please confirm the statement above.' : null,
  ][step]

  function chooseSample(sample: ChosenSample) { // demo mode: the sample's details and images, as the real run used
    setDemoSample(sample.id)
    setDetails({ fullName: sample.fullName, dateOfBirth: sample.dateOfBirth })
    setShowErrors(false)
    void documentImage.pick(sample.document, `Sample ${sample.id}: ID document`)
    void selfieImage.pick(sample.selfie, `Sample ${sample.id}: selfie`)
  }

  function goTo(next: number) {
    setShowErrors(false)
    setSubmitError(null)
    setStep(next)
  }

  async function next() {
    if (problem) {
      setShowErrors(true)
      return
    }
    if (step < STEPS.length - 1) {
      goTo(step + 1)
      return
    }
    if (!documentImage.picked || !selfieImage.picked) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const created = await api.submitApplication({ fullName: details.fullName.trim(), dateOfBirth: details.dateOfBirth,
        idImage: documentImage.picked.blob, selfie: selfieImage.picked.blob })
      navigate(`/customer/applications/${created.application_id}`)
    } catch (err) {
      setSubmitError(messageOf(err))
      setSubmitting(false)
    }
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h1" sx={{ mb: 0.5 }}>Verify your identity</Typography>
        <Typography color="text.secondary">Four short steps. Have your passport or ID card ready.</Typography>
      </Box>
      <Stepper activeStep={step} alternativeLabel aria-label="Verification steps">
        {STEPS.map((s) => <Step key={s.label}><StepLabel>{s.label}</StepLabel></Step>)}
      </Stepper>
      <Paper component="section" aria-labelledby="step-title" sx={{ p: { xs: 2, sm: 3 } }}>
        <Typography id="step-title" variant="h2" component="h2" ref={headingRef} tabIndex={-1} sx={{ mb: 2, outline: 'none' }}>
          Step {step + 1} of {STEPS.length}: {STEPS[step].title}
        </Typography>

        {step === 0 && (__DEMO_MODE__ ? (
          <DemoSampleStep chosen={demoSample} error={showErrors ? detailsProblem : null} onChoose={chooseSample} />
        ) : (
          <PersonalDetailsStep value={details} today={today} onChange={setDetails}
            errors={showErrors ? personalErrors : {}} />
        ))}
        {step === 1 && (__DEMO_MODE__ ? <DemoImageStep kind="document" picked={documentImage.picked} /> : (
          <DocumentStep picked={documentImage.picked} onClear={documentImage.clear}
            onFile={(file) => void documentImage.pick(file, file.name)} />
        ))}
        {step === 2 && (__DEMO_MODE__ ? <DemoImageStep kind="selfie" picked={selfieImage.picked} /> : (
          <SelfieStep picked={selfieImage.picked} onClear={selfieImage.clear}
            onCapture={(photo) => void selfieImage.pick(photo, 'Camera photo')}
            onFile={(file) => void selfieImage.pick(file, file.name)} />
        ))}
        {step === 3 && documentImage.picked && selfieImage.picked && (
          <ReviewStep details={details} documentUrl={documentImage.picked.url} selfieUrl={selfieImage.picked.url}
            consent={consent} consentError={showErrors && !consent} onConsent={setConsent} onEdit={goTo} />
        )}

        {showErrors && problem && step > 0 && step < 3 && <Alert severity="error" sx={{ mt: 2 }} role="alert">{problem}</Alert>}
        {submitError && <Alert severity="error" sx={{ mt: 2 }} role="alert">{submitError}</Alert>}

        <Stack direction="row" spacing={2} sx={{ mt: 3, justifyContent: 'space-between' }}>
          <Button startIcon={<ArrowBackIcon />} onClick={() => goTo(step - 1)} disabled={step === 0 || submitting}>Back</Button>
          <Button variant="contained" size="large" onClick={next} disabled={submitting}
            endIcon={submitting ? <CircularProgress size={18} color="inherit" /> : step === 3 ? <SendIcon /> : <ArrowForwardIcon />}>
            {step === 3 ? (submitting ? 'Submitting…' : 'Submit') : 'Continue'}
          </Button>
        </Stack>
      </Paper>
    </Stack>
  )
}
